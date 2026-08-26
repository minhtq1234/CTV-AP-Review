import json
import os
import tempfile
import unittest

from PIL import Image

import cccd_manual as cm


def _png(path: str, size=(40, 25)) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    Image.new("RGB", size, (200, 200, 200)).save(path)


def _side(source_path: str, drawing_id: str) -> dict:
    return {
        "drawingId": drawing_id,
        "mediaType": "image/png",
        "width": 40,
        "height": 25,
        "sha256": "a" * 64,
        "sourcePath": source_path,
        "packetPath": None,
        "anchor": {
            "sheet": "CCCD",
            "fromRow": 1,
            "fromCol": 0,
            "toRow": 2,
            "toCol": 1,
        },
    }


class ManualAssignment(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.case_dir = self.tmp.name
        _png(os.path.join(self.case_dir, "cccd-assets/extracted/d1.png"))
        _png(os.path.join(self.case_dir, "cccd-assets/extracted/d2.png"))
        self.manifest_paths = {}
        for index in (0, 1):
            path = os.path.join(
                self.case_dir, "packets", str(index), "manifest.json"
            )
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(
                    {
                        "docs": [],
                        "fields": [{"key": "cccd", "sources": []}],
                    },
                    handle,
                )
            self.manifest_paths[index] = path
        self.case = {
            "packets": [{"index": 0}, {"index": 1}],
            "cccdWorkbook": {
                "status": "ready",
                "summary": {
                    "candidates": 2,
                    "attached": 0,
                    "unresolved": 2,
                },
                "mappings": [
                    {
                        "candidateId": "card-a",
                        "front": None,
                        "back": None,
                        "unknown": _side(
                            "cccd-assets/extracted/d1.png", "d1"
                        ),
                        "ocrIdentity": {"cccd": "", "name": ""},
                        "state": "manual",
                        "attachedPacketIndex": None,
                        "matchMethod": None,
                        "issues": ["unknown-side"],
                    },
                    {
                        "candidateId": "card-b",
                        "front": _side(
                            "cccd-assets/extracted/d2.png", "d2"
                        ),
                        "back": None,
                        "unknown": None,
                        "ocrIdentity": {"cccd": "012345678901", "name": ""},
                        "state": "manual",
                        "attachedPacketIndex": None,
                        "matchMethod": None,
                        "issues": ["missing-back"],
                    },
                ],
            },
        }

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _docs(self, index: int) -> list[dict]:
        with open(self.manifest_paths[index], encoding="utf-8") as handle:
            return json.load(handle)["docs"]

    def _assign(self, card_id, packet_index):
        return cm.assign_card(
            self.case,
            card_id,
            packet_index,
            self.case_dir,
            self.manifest_paths,
        )

    def test_lists_every_card_without_paths(self):
        cards = cm.list_cards(self.case)
        self.assertEqual([c["cardId"] for c in cards], ["card-a", "card-b"])
        self.assertEqual(cards[0]["sides"][0]["side"], "unknown")
        self.assertNotIn("sourcePath", json.dumps(cards))

    def test_attached_card_reports_its_packet(self):
        self._assign("card-a", 0)
        by_id = {c["cardId"]: c for c in cm.list_cards(self.case)}
        self.assertEqual(by_id["card-a"]["attachedPacketIndex"], 0)
        self.assertIsNone(by_id["card-b"]["attachedPacketIndex"])

    def test_unknown_side_card_attaches_as_a_front(self):
        self._assign("card-a", 0)
        docs = self._docs(0)
        self.assertEqual([d["kind"] for d in docs], ["id_front"])
        self.assertTrue(os.path.isfile(docs[0]["pages"][0]["src"]))
        mapping = self.case["cccdWorkbook"]["mappings"][0]
        self.assertEqual(mapping["attachedPacketIndex"], 0)
        self.assertEqual(mapping["state"], "assigned")
        self.assertEqual(mapping["matchMethod"], "manual")

    def test_front_only_card_attaches_without_a_back(self):
        self._assign("card-b", 1)
        self.assertEqual([d["kind"] for d in self._docs(1)], ["id_front"])

    def test_moving_a_card_leaves_nothing_behind(self):
        self._assign("card-a", 0)
        old_file = self._docs(0)[0]["pages"][0]["src"]
        self._assign("card-a", 1)
        self.assertEqual(self._docs(0), [])
        self.assertFalse(os.path.exists(old_file))
        self.assertEqual([d["kind"] for d in self._docs(1)], ["id_front"])

    def test_detaching_removes_the_evidence(self):
        self._assign("card-a", 0)
        self._assign("card-a", None)
        self.assertEqual(self._docs(0), [])
        mapping = self.case["cccdWorkbook"]["mappings"][0]
        self.assertIsNone(mapping["attachedPacketIndex"])
        self.assertEqual(mapping["state"], "manual")

    def test_a_packet_holds_at_most_one_card(self):
        self._assign("card-a", 0)
        with self.assertRaises(cm.CccdManualError) as caught:
            self._assign("card-b", 0)
        self.assertEqual(caught.exception.code, "packet-already-has-card")

    def test_summary_tracks_attachment(self):
        self._assign("card-a", 0)
        self.assertEqual(
            self.case["cccdWorkbook"]["summary"],
            {"candidates": 2, "attached": 1, "unresolved": 1},
        )

    def test_unknown_packet_is_refused(self):
        with self.assertRaises(cm.CccdManualError) as caught:
            self._assign("card-a", 7)
        self.assertEqual(caught.exception.code, "unknown-packet")

    def test_unknown_card_is_refused(self):
        with self.assertRaises(cm.CccdManualError) as caught:
            self._assign("card-zzz", 0)
        self.assertEqual(caught.exception.code, "card-not-found")

    def test_side_path_stays_inside_the_case(self):
        self.case["cccdWorkbook"]["mappings"][0]["unknown"]["sourcePath"] = (
            "../../../etc/passwd"
        )
        with self.assertRaises(cm.CccdManualError) as caught:
            cm.card_side_path(self.case, self.case_dir, "card-a", "unknown")
        self.assertEqual(caught.exception.code, "side-not-found")


if __name__ == "__main__":
    unittest.main()

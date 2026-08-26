import unittest

import cccd_idp as idp


def envelope(values, *, classification=True, title="Căn cước công dân"):
    """An IDP result shaped like the live one."""
    return {
        "data": {
            "status": "COMPLETED",
            "documents": [{
                "document_type_title": title,
                "is_correct": False,  # False even on perfect reads -- see module
                "is_correct_classification": classification,
                "ocr_data": [{
                    "name": "eid",
                    "value": [
                        {
                            "name": name,
                            "extracted_value": value,
                            "extracted_prob": 0.97,
                            "coordinates": [1, 2, 3, 4],
                        }
                        for name, value in values.items()
                    ],
                }],
            }],
        }
    }


ROSTER = [
    {"name": "Trần Thanh Vân Anh", "cccd": "079303009457"},
    {"name": "Nguyễn Văn An", "cccd": "001204004530"},
    {"name": "Lê Thị Thu Hà", "cccd": "042198013828"},
]


class ParsingResults(unittest.TestCase):
    def test_reads_the_named_fields(self):
        read = idp.parse_result(envelope({
            "id_number": "079303009457",
            "name": "Trần Thanh Vân Anh",
            "dob": "03/09/2003",
            "address": "somewhere",
        }))
        self.assertEqual(read.id_number, "079303009457")
        self.assertEqual(read.name, "Trần Thanh Vân Anh")
        self.assertEqual(read.dob, "03/09/2003")
        self.assertTrue(read.has_identity)
        self.assertIn("address", read.fields)

    def test_a_card_back_yields_no_identity(self):
        # A back carries issue date, issuing office, features, signer -- and no
        # identity number. It must not be coerced into one.
        read = idp.parse_result(envelope({
            "doi": "13/10/2025",
            "poi": "Cục Cảnh sát quản lý hành chính về trật tự xã hội",
            "features": "Sẹo chấm cách 1cm",
            "signer": "Nguyễn Văn X",
        }))
        self.assertEqual(read.id_number, "")
        self.assertFalse(read.has_identity)

    def test_a_nine_digit_cmnd_is_not_treated_as_a_cccd(self):
        read = idp.parse_result(envelope({"id_number": "012345678"}))
        self.assertEqual(read.id_number, "")

    def test_spaced_numbers_are_normalised(self):
        read = idp.parse_result(envelope({"id_number": "079 303 009 457"}))
        self.assertEqual(read.id_number, "079303009457")


class Deciding(unittest.TestCase):
    def decide(self, values, classification=True):
        return idp.decide(
            idp.parse_result(envelope(values, classification=classification)),
            ROSTER,
        )

    def test_number_and_name_agreeing_may_attach(self):
        decision = self.decide({
            "id_number": "079303009457",
            "name": "Trần Thanh Vân Anh",
        })
        self.assertEqual(decision.action, "attach")
        self.assertEqual(decision.roster_index, 0)
        self.assertEqual(decision.reason, "number-and-name-agree")

    def test_accent_loss_still_agrees(self):
        # OCR drops Vietnamese tone marks routinely; that alone must not block.
        decision = self.decide({
            "id_number": "079303009457",
            "name": "TRAN THANH VAN ANH",
        })
        self.assertEqual(decision.action, "attach")

    def test_a_disagreeing_name_never_attaches(self):
        decision = self.decide({
            "id_number": "079303009457",
            "name": "Nguyễn Văn An",
        })
        self.assertEqual(decision.action, "review")
        self.assertEqual(decision.reason, "name-disagrees")
        self.assertEqual(decision.roster_index, 0)

    def test_a_number_alone_is_not_enough(self):
        decision = self.decide({"id_number": "079303009457"})
        self.assertEqual(decision.action, "review")
        self.assertEqual(decision.reason, "no-name-to-corroborate")

    def test_a_number_matching_nobody_goes_to_review(self):
        decision = self.decide({
            "id_number": "999999999999",
            "name": "Trần Thanh Vân Anh",
        })
        self.assertEqual(decision.action, "review")
        self.assertEqual(decision.reason, "no-roster-match")

    def test_a_back_goes_to_review(self):
        decision = self.decide({"doi": "13/10/2025", "signer": "X"})
        self.assertEqual(decision.reason, "no-identity-number")

    def test_an_unrecognised_document_goes_to_review(self):
        decision = self.decide(
            {"id_number": "079303009457", "name": "Trần Thanh Vân Anh"},
            classification=False,
        )
        self.assertEqual(decision.reason, "not-recognised-as-id")

    def test_a_duplicated_roster_cccd_is_ambiguous(self):
        roster = ROSTER + [{"name": "Someone Else", "cccd": "079303009457"}]
        read = idp.parse_result(envelope({
            "id_number": "079303009457",
            "name": "Trần Thanh Vân Anh",
        }))
        self.assertEqual(idp.decide(read, roster).reason, "duplicate-roster-cccd")


class Polling(unittest.TestCase):
    """The envelope reports a terminal status before ocr_data is populated."""

    def test_waits_for_fields_not_for_status(self):
        empty = {"data": {"status": "COMPLETED", "documents": [
            {"ocr_data": [{"name": "eid", "value": []}]}
        ]}}
        full = envelope({"id_number": "042198013828", "name": "Lê Thị Thu Hà"})
        responses = [empty, empty, full]
        calls = []

        def fetch(request_id):
            calls.append(request_id)
            return responses[min(len(calls) - 1, len(responses) - 1)]

        read = idp.read_card(
            b"jpeg",
            "card.jpg",
            submit=lambda *_: {"data": {"request_id": "abc"}},
            fetch=fetch,
            sleep=lambda _s: None,
        )
        # status said COMPLETED on the first read; only content ends the wait
        self.assertEqual(read.id_number, "042198013828")
        self.assertEqual(len(calls), 3)

    def test_a_missing_request_id_is_an_error(self):
        with self.assertRaises(idp.IdpError):
            idp.read_card(
                b"jpeg", "card.jpg",
                submit=lambda *_: {"data": {}},
                fetch=lambda _rid: {},
                sleep=lambda _s: None,
            )

    def test_a_dead_job_stops_polling(self):
        dead = {"data": {"status": "FAILED", "documents": []}}
        calls = []
        read = idp.read_card(
            b"jpeg", "card.jpg",
            submit=lambda *_: {"data": {"request_id": "abc"}},
            fetch=lambda rid: (calls.append(rid), dead)[1],
            sleep=lambda _s: None,
        )
        self.assertEqual(read.id_number, "")
        self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main()


class AdaptingToThePipeline(unittest.TestCase):
    """IDP must speak the shape the rest of the ingest already understands."""

    OMIT = object()

    def ocr(self, values, coordinates=None):
        payload = envelope(values)
        if coordinates is not None:
            for item in payload["data"]["documents"][0]["ocr_data"][0]["value"]:
                if item["name"] != "id_number":
                    continue
                if coordinates is self.OMIT:
                    item.pop("coordinates", None)
                else:
                    item["coordinates"] = coordinates
        return idp.as_image_ocr(idp.parse_result(payload))

    def test_a_face_with_a_number_is_a_front(self):
        ocr = self.ocr({"id_number": "079303009457", "name": "Trần Thanh Vân Anh"})
        self.assertEqual(ocr.side, "front")
        self.assertEqual(ocr.cccd, "079303009457")
        self.assertEqual(ocr.name, "Trần Thanh Vân Anh")
        self.assertGreater(ocr.cccd_confidence, 0.9)

    def test_issue_and_authority_fields_make_a_back(self):
        ocr = self.ocr({"doi": "13/10/2025", "poi": "Cục Cảnh sát", "signer": "X"})
        self.assertEqual(ocr.side, "back")
        self.assertEqual(ocr.cccd, "")
        self.assertEqual(ocr.cccd_confidence, 0.0)

    def test_neither_is_unknown(self):
        self.assertEqual(self.ocr({"address": "somewhere"}).side, "unknown")

    def test_corner_coordinates_become_a_box(self):
        ocr = self.ocr({"id_number": "079303009457"}, coordinates=[10, 20, 110, 60])
        self.assertEqual(
            ocr.number_bbox, {"x": 10, "y": 20, "width": 100, "height": 40}
        )

    def test_origin_and_size_coordinates_also_work(self):
        # (x, y, w, h): the last two do not exceed the first two
        ocr = self.ocr({"id_number": "079303009457"}, coordinates=[100, 200, 80, 30])
        self.assertEqual(
            ocr.number_bbox, {"x": 100, "y": 200, "width": 80, "height": 30}
        )

    def test_a_missing_or_degenerate_box_is_none(self):
        self.assertIsNone(
            self.ocr({"id_number": "079303009457"}, coordinates=self.OMIT).number_bbox
        )
        self.assertIsNone(
            self.ocr({"id_number": "079303009457"}, coordinates=[5, 5, 0, 0]).number_bbox
        )
        self.assertIsNone(
            self.ocr({"id_number": "079303009457"}, coordinates=["a", "b", "c", "d"]).number_bbox
        )

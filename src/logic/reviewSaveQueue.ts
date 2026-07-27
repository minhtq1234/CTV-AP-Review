import type { PacketReview } from '../upload/api'

export interface ReviewSaveContext {
  caseId: string
  packetIndex: number
}

export function createReviewSaveQueue<Result>(
  save: (context: ReviewSaveContext, review: PacketReview) => Promise<Result>,
) {
  const tails = new Map<string, Promise<void>>()

  return {
    enqueue(context: ReviewSaveContext, review: PacketReview): Promise<Result> {
      const key = `${context.caseId}:${context.packetIndex}`
      const previous = tails.get(key) ?? Promise.resolve()
      const operation = previous.then(() => save(context, review))
      const settled = operation.then(
        () => undefined,
        () => undefined,
      )
      tails.set(key, settled)
      void settled.then(() => {
        if (tails.get(key) === settled) tails.delete(key)
      })
      return operation
    },
  }
}

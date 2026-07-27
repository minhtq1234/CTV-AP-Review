import { describe, expect, test } from 'vitest'
import type { PacketReview } from '../upload/api'
import { createReviewSaveQueue } from './reviewSaveQueue'

const review = (done: boolean): PacketReview => ({
  done,
  fields: {},
  rejection: null,
})

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (reason?: unknown) => void
  const promise = new Promise<T>((res, rej) => {
    resolve = res
    reject = rej
  })
  return { promise, resolve, reject }
}

describe('review save queue', () => {
  test('serializes full review snapshots for the same packet', async () => {
    const first = deferred<string>()
    const started: boolean[] = []
    const queue = createReviewSaveQueue(async (_context, candidate) => {
      started.push(candidate.done)
      if (!candidate.done) return first.promise
      return 'second'
    })
    const context = { caseId: 'case-a', packetIndex: 0 }
    const firstResult = queue.enqueue(context, review(false))
    const secondResult = queue.enqueue(context, review(true))

    await Promise.resolve()
    expect(started).toEqual([false])
    first.resolve('first')
    await expect(firstResult).resolves.toBe('first')
    await expect(secondResult).resolves.toBe('second')
    expect(started).toEqual([false, true])
  })

  test('continues with the next save after an earlier failure', async () => {
    const started: boolean[] = []
    const queue = createReviewSaveQueue(async (_context, candidate) => {
      started.push(candidate.done)
      if (!candidate.done) throw new Error('save failed')
      return 'recovered'
    })
    const context = { caseId: 'case-a', packetIndex: 0 }

    await expect(queue.enqueue(context, review(false))).rejects.toThrow('save failed')
    await expect(queue.enqueue(context, review(true))).resolves.toBe('recovered')
    expect(started).toEqual([false, true])
  })

  test('captures case and packet context for every operation', async () => {
    const contexts: string[] = []
    const queue = createReviewSaveQueue(async (context) => {
      contexts.push(`${context.caseId}:${context.packetIndex}`)
      return context.packetIndex
    })
    const contextA = { caseId: 'case-a', packetIndex: 0 }
    const contextB = { caseId: 'case-b', packetIndex: 3 }

    await expect(queue.enqueue(contextA, review(false))).resolves.toBe(0)
    await expect(queue.enqueue(contextB, review(true))).resolves.toBe(3)
    expect(contexts).toEqual(['case-a:0', 'case-b:3'])
  })

  test('different packets do not block each other', async () => {
    const blocked = deferred<string>()
    const queue = createReviewSaveQueue(async (context) => {
      if (context.packetIndex === 0) return blocked.promise
      return 'packet-b'
    })

    const packetA = queue.enqueue(
      { caseId: 'case-a', packetIndex: 0 },
      review(false),
    )
    await expect(queue.enqueue(
      { caseId: 'case-a', packetIndex: 1 },
      review(true),
    )).resolves.toBe('packet-b')
    blocked.resolve('packet-a')
    await expect(packetA).resolves.toBe('packet-a')
  })
})

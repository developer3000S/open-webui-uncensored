import { describe, it, expect } from 'vitest';
import { serverProgressToFileProgress } from './src/lib/apis/files/index';

describe('serverProgressToFileProgress', () => {
  it('returns null for missing progress', () => {
    expect(serverProgressToFileProgress(null)).toBeNull();
    expect(serverProgressToFileProgress(undefined)).toBeNull();
  });

  it('maps a server tick onto the processing half of the bar', () => {
    expect(
      serverProgressToFileProgress({
        phase: 'embedding',
        percent: 0.4,
        processed_chunks: 2,
        total_chunks: 5
      })
    ).toEqual({
      phase: 'embedding',
      percent: 0.7,
      processed_chunks: 2,
      total_chunks: 5
    });
  });
});
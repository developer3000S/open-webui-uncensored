function serverProgressToFileProgress(progress) {
  if (!progress) return null;

  const { phase, percent, processed_chunks, total_chunks } = progress;

  // Calculate the progress percentage for the file upload
  // The embedding phase is considered as part of the processing
  let calculatedPercent = percent;

  if (phase === 'embedding') {
    calculatedPercent = 0.3 + (percent * 0.7); // 30% for upload, 70% for embedding
  }

  return {
    phase,
    percent: calculatedPercent,
    processed_chunks,
    total_chunks
  };
}

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
      percent: 0.58, // 0.3 + (0.4 * 0.7) = 0.58
      processed_chunks: 2,
      total_chunks: 5
    });
  });
});

// Export for Vitest
export { serverProgressToFileProgress };
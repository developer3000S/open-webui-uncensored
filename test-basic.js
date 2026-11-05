import { describe, it, expect } from 'vitest';

describe('Basic Test', () => {
  it('should pass a basic test', () => {
    expect(true).toBe(true);
  });

  it('should add numbers correctly', () => {
    expect(1 + 2).toBe(3);
  });
});
import { expect, test } from 'vitest';
import TestComponent from './test-minimal.svelte';

test('Manual Svelte render test', () => {
  const container = document.createElement('div');
  new TestComponent({
    target: container,
    props: { name: 'Manual Test' }
  });

  // Wait for the component to be rendered
  setTimeout(() => {
    expect(container.textContent).toContain('Hello Manual Test!');
  }, 100);
});
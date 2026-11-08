import { expect, test } from 'vitest';
import { render } from '@testing-library/svelte';
import TestComponent from './test-minimal.svelte';

test('Manual Svelte render test', async () => {
  const { container } = render(TestComponent, {
    props: { name: 'Manual Test' }
  });

  await new Promise(resolve => setTimeout(resolve, 100));
  expect(container.textContent).toContain('Hello Manual Test!');
});
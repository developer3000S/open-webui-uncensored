import { expect, test } from 'vitest';
import { render } from '@testing-library/svelte';
import TestComponent from './test-minimal.svelte';

test('Svelte component test', () => {
  const { container } = render(TestComponent, {
    props: { name: 'Direct Test' }
  });

  expect(container.textContent).toContain('Hello Direct Test!');
});
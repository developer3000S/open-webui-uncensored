import { expect, test } from 'vitest';
import { createSvelte } from 'svelte/internal';
import TestComponent from './test-minimal.svelte';

test('Svelte component test', () => {
  const { component, html } = createSvelte(TestComponent, {
    target: document.body,
    props: { name: 'Direct Test' }
  });

  expect(document.body.textContent).toContain('Hello Direct Test!');
});
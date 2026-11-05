import { render } from '@testing-library/svelte';
import { describe, it, expect } from 'vitest';
import TestComponent from './test-minimal.svelte';

describe('Minimal Svelte Test', () => {
  it('should render correctly', () => {
    const { getByText } = render(TestComponent, {
      props: { name: 'Svelte' }
    });
    expect(getByText('Hello Svelte!')).toBeInTheDocument();
  });
});
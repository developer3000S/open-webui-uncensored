import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';
import SearchInput from './SearchInput.svelte';
import { getAllTags } from '$lib/apis/chats';

// Mock the getAllTags function
vi.mock('$lib/apis/chats', () => ({
    getAllTags: vi.fn().mockResolvedValue([
        { id: 'tag1', name: 'Tag 1' },
        { id: 'tag2', name: 'Tag 2' }
    ])
}));

describe('SearchInput', () => {
    beforeEach(() => {
        vi.clearAllMocks();
    });

    it('renders the search input', () => {
        const { getByPlaceholderText } = render(SearchInput, {
            props: {
                placeholder: 'Search'
            }
        });
        
        const input = getByPlaceholderText('Search');
        expect(input).toBeTruthy();
    });

    it('accepts and displays values', async () => {
        const { getByPlaceholderText } = render(SearchInput, {
            props: {
                placeholder: 'Search',
                value: 'test query'
            }
        });
        
        const input = getByPlaceholderText('Search') as HTMLInputElement;
        expect(input.value).toBe('test query');
    });

    it('shows clear button when showClearButton is true and value is set', async () => {
        const { getByRole } = render(SearchInput, {
            props: {
                placeholder: 'Search',
                value: 'test query',
                showClearButton: true
            }
        });
        
        const clearButton = getByRole('button');
        expect(clearButton).toBeTruthy();
    });

    it('clears input when clear button is clicked', async () => {
        const { getByRole, getByPlaceholderText } = render(SearchInput, {
            props: {
                placeholder: 'Search',
                value: 'test query',
                showClearButton: true
            }
        });
        
        const clearButton = getByRole('button');
        await fireEvent.click(clearButton);
        
        const input = getByPlaceholderText('Search') as HTMLInputElement;
        expect(input.value).toBe('');
    });

    it('calls onFocus callback when input is focused', async () => {
        const onFocus = vi.fn();
        const { getByPlaceholderText } = render(SearchInput, {
            props: {
                placeholder: 'Search',
                onFocus
            }
        });
        
        const input = getByPlaceholderText('Search');
        await fireEvent.focus(input);
        
        expect(onFocus).toHaveBeenCalled();
    });

    it('calls onKeydown callback when key is pressed', async () => {
        const onKeydown = vi.fn();
        const { getByPlaceholderText } = render(SearchInput, {
            props: {
                placeholder: 'Search',
                onKeydown
            }
        });
        
        const input = getByPlaceholderText('Search');
        await fireEvent.keyDown(input, { key: 'Enter' });
        
        expect(onKeydown).toHaveBeenCalled();
    });
});
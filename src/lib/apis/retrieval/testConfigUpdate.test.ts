import { describe, it, expect, vi } from 'vitest';
import { updateRAGConfig } from './index';
import { RETRIEVAL_API_BASE_URL } from '$lib/constants';

// Mock fetch
global.fetch = vi.fn();

describe('updateRAGConfig', () => {
    it('should update RAG configuration successfully', async () => {
        const mockResponse = {
            ok: true,
            json: vi.fn().mockResolvedValue({ success: true })
        };
        (fetch as any).mockResolvedValue(mockResponse);

        const result = await updateRAGConfig('test-token', {
            PDF_EXTRACT_IMAGES: true
        });

        expect(fetch).toHaveBeenCalledWith(
            `${RETRIEVAL_API_BASE_URL}/config/update`,
            expect.objectContaining({
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': 'Bearer test-token'
                },
                body: JSON.stringify({ PDF_EXTRACT_IMAGES: true })
            })
        );
        expect(result).toEqual({ success: true });
    });

    it('should handle errors when configuration update fails', async () => {
        const mockResponse = {
            ok: false,
            json: vi.fn().mockResolvedValue({ detail: 'Failed to update configuration' })
        };
        (fetch as any).mockResolvedValue(mockResponse);

        await expect(updateRAGConfig('test-token', {})).rejects.toThrow('Failed to update configuration');
    });
});
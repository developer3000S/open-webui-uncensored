import { updateRAGConfig } from './index';

// Test configuration
const testToken = 'test-token';
const testConfig = {
    PDF_EXTRACT_IMAGES: true,
    ENABLE_GOOGLE_DRIVE_INTEGRATION: true,
    chunk: {
        chunk_size: 1000,
        chunk_overlap: 200
    }
};

// Test the update function
async function testConfigUpdate() {
    try {
        const result = await updateRAGConfig(testToken, testConfig);
        console.log('Configuration updated successfully:', result);
    } catch (error) {
        console.error('Failed to update configuration:', error);
    }
}

testConfigUpdate();
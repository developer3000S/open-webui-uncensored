export const ssr = false;

export const trailingSlash = 'ignore';

import type { LayoutLoad } from './$types';

export const load: LayoutLoad = async () => {
    return {
        pageTitle: 'Open WebUI',
        user: { name: 'Guest' },
    };
};

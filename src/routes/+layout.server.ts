import type { LayoutServerLoad } from './$types';

export const load: LayoutServerLoad = async () => {
    // Здесь можно добавить логику загрузки данных, которые будут доступны в компоненте +layout.svelte
    // через export let data.
    return {
        // Пример данных, которые можно передать
        pageTitle: 'Open WebUI',
        user: { name: 'Guest' },
    };
};
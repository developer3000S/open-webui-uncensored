// Accent palettes for the chat top status bar. Each theme keeps OWUI's own
// dark/light class switch and only restyles the accent colour, so the picker
// stays orthogonal to the "Dark/Light/System" mode toggle.

export type AccentTheme = {
	id: string;
	name: string;
	/** 'dark' | 'light' — which OWUI mode this accent is meant for. */
	mode: 'dark' | 'light';
	primary: string;
	secondary: string;
};

export const ACCENT_THEMES: AccentTheme[] = [
	{ id: 'indigo', name: 'Индиго (по умолчанию)', mode: 'dark', primary: '#6366f1', secondary: '#38bdf8' },
	{ id: 'cyberpunk', name: 'Киберпанк (неон)', mode: 'dark', primary: '#ff007f', secondary: '#00f0ff' },
	{ id: 'dracula', name: 'Dracula', mode: 'dark', primary: '#bd93f9', secondary: '#ff79c6' },
	{ id: 'forest', name: 'Изумрудный лес', mode: 'dark', primary: '#10b981', secondary: '#34d399' },
	{ id: 'nord', name: 'Nord', mode: 'dark', primary: '#5e81ac', secondary: '#88c0d0' },
	{ id: 'amber', name: 'Янтарь', mode: 'light', primary: '#d97706', secondary: '#0ea5e9' },
	{ id: 'sakura', name: 'Сакура', mode: 'light', primary: '#d05a74', secondary: '#e597a7' },
	{ id: 'ocean', name: 'Океан', mode: 'light', primary: '#0284c7', secondary: '#14b8a6' }
];

const ACCENT_VARS = ['--accent-primary', '--accent-secondary'] as const;

// Tailwind v4 reads these as `--color-primary-500` / `--color-primary-600`,
// so `bg-primary-500` & friends follow the chosen palette automatically.
const TAILWIND_VARS = ['--color-primary-500', '--color-primary-600', '--color-primary-700'] as const;

// Map of the Tailwind utilities this project actually uses for accents, to the
// variables each one must set. Kept in one place so a new utility only needs
// one line here plus its `@utility` rule in tailwind.css.
const UTILITY_VARS: Record<string, string[]> = {
	'bg-primary': ['--accent-primary'],
	'text-primary': ['--accent-primary'],
	'border-primary': ['--accent-primary'],
	'ring-primary': ['--accent-primary'],
	'bg-secondary': ['--accent-secondary'],
	'text-secondary': ['--accent-secondary']
};

const hexToRgb = (hex: string) => {
	const value = hex.replace('#', '');
	const bigint = parseInt(
		value.length === 3 ? value.split('').map((c) => c + c).join('') : value,
		16
	);
	return [(bigint >> 16) & 255, (bigint >> 8) & 255, bigint & 255];
};

const withAlpha = (hex: string, alpha: number) => {
	const [r, g, b] = hexToRgb(hex);
	return `rgb(${r} ${g} ${b} / ${alpha})`;
};

export const applyAccentTheme = (themeId: string | null) => {
	const theme = ACCENT_THEMES.find((t) => t.id === themeId);
	if (!theme) {
		[...ACCENT_VARS, ...TAILWIND_VARS, ...Object.values(UTILITY_VARS).flat()].forEach((v) =>
			document.documentElement.style.removeProperty(v)
		);
		localStorage.removeItem('accent-theme');
		return;
	}

	document.documentElement.style.setProperty('--accent-primary', theme.primary);
	document.documentElement.style.setProperty('--accent-secondary', theme.secondary);

	// rgb() triplets are what the `@utility` rules in tailwind.css consume
	// (color-mix() needs a real colour, not a hex shorthand property value).
	TAILWIND_VARS.forEach((v) =>
		document.documentElement.style.setProperty(v, hexToRgb(theme.primary).join(' '))
	);

	Object.entries(UTILITY_VARS).forEach(([_utility, vars]) => {
		vars.forEach((v) => {
			const hex = v === '--accent-secondary' ? theme.secondary : theme.primary;
			document.documentElement.style.setProperty(v, hex);
			document.documentElement.style.setProperty(
				`${v}-rgb`,
				hexToRgb(hex).join(' ')
			);
		});
	});

	// Translucent variants for hover/focus states.
	document.documentElement.style.setProperty('--accent-primary-soft', withAlpha(theme.primary, 0.1));
	document.documentElement.style.setProperty('--accent-secondary-soft', withAlpha(theme.secondary, 0.1));

	localStorage.setItem('accent-theme', theme.id);
};

export const getStoredAccentTheme = (): string | null => {
	try {
		return localStorage.getItem('accent-theme');
	} catch {
		return null;
	}
};

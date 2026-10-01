<script lang="ts">
	import { onMount, onDestroy, getContext } from 'svelte';
	import { theme, models, temporaryChatEnabled } from '$lib/stores';
	import { getTelemetry } from '$lib/apis/telemetry';
	import { ACCENT_THEMES, applyAccentTheme, getStoredAccentTheme } from '$lib/themes';

	import Tooltip from '$lib/components/common/Tooltip.svelte';
	import Sun from '$lib/components/icons/Sun.svelte';
	import Moon from '$lib/components/icons/Moon.svelte';
	import Palette from '$lib/components/icons/Palette.svelte';
	import Cpu from '$lib/components/icons/Cpu.svelte';
	import Check from '$lib/components/icons/Check.svelte';

	const i18n = getContext('i18n');

	export let selectedModels: string[] = [];

	const THEMES = ['dark', 'light', 'oled-dark', 'system'] as const;
	const allThemes = [...THEMES, 'her'];

	// Chat mode shown in the status section: model name when one is picked, or
	// the mode the chat will run in otherwise (temporary chat / local model server).
	let workMode = $i18n.t('Local Mode');
	let workModeActive = false;

	$: {
		const modelId = selectedModels?.[0];
		const model = modelId ? $models.find((m) => m.id === modelId) : null;

		if (model) {
			workMode = model.name;
			workModeActive = true;
		} else if ($temporaryChatEnabled) {
			workMode = $i18n.t('Temporary Chat');
			workModeActive = true;
		} else {
			workMode = $i18n.t('Local Mode');
			workModeActive = false;
		}
	}

	let isDark = true;
	$: {
		const current = $theme ?? 'system';
		if (current === 'system') {
			isDark = typeof window !== 'undefined'
				? window.matchMedia('(prefers-color-scheme: dark)').matches
				: true;
		} else {
			isDark = current === 'dark' || current === 'oled-dark';
		}
	}

	const toggleTheme = () => {
		applyThemeMode(isDark ? 'light' : 'dark');
	};

	// Mirrors the class/`localStorage.theme` handling of the theme pipeline in
	// Settings/General.svelte (+layout.svelte listens for `theme:update` too).
	const applyThemeMode = (_theme: string) => {
		localStorage.setItem('theme', _theme);
		theme.set(_theme);

		const themeToApply =
			_theme === 'oled-dark' ? 'dark' : _theme === 'her' ? 'light' : _theme;

		allThemes
			.filter((e) => e !== themeToApply)
			.forEach((e) => {
				e.split(' ').forEach((cls) => document.documentElement.classList.remove(cls));
			});

		themeToApply.split(' ').forEach((cls) => document.documentElement.classList.add(cls));

		if (typeof window !== 'undefined' && window.applyTheme) {
			window.applyTheme();
		}
	};

	// --- Accent theme picker -------------------------------------------------
	let showAccentMenu = false;
	let accentMenuEl: HTMLElement;
	let selectedAccent = getStoredAccentTheme();

	const toggleAccentMenu = () => {
		showAccentMenu = !showAccentMenu;
	};

	const handleWindowClick = (e: MouseEvent) => {
		if (showAccentMenu && accentMenuEl && !accentMenuEl.contains(e.target as Node)) {
			showAccentMenu = false;
		}
	};

	const selectAccent = (themeId: string) => {
		if (selectedAccent === themeId) {
			selectedAccent = null;
			applyAccentTheme(null);
		} else {
			selectedAccent = themeId;
			applyAccentTheme(themeId);
		}
		showAccentMenu = false;
	};

	// --- Telemetry ----------------------------------------------------------
	let telemetry = {
		cpu_usage: null as null | number,
		ram_used_gb: null as null | number,
		ram_total_gb: null as null | number
	};

	let pollInterval: ReturnType<typeof setInterval>;

	const formatGb = (value: null | number) => {
		if (value === null || value === undefined || !Number.isFinite(value)) return '--';
		return value.toFixed(value >= 10 ? 0 : 1);
	};

	const refreshTelemetry = async () => {
		try {
			const token = localStorage.token;
			if (!token) return;
			telemetry = await getTelemetry(token);
		} catch (err) {
			console.error('Failed to fetch telemetry', err);
		}
	};

	onMount(() => {
		refreshTelemetry();
		pollInterval = setInterval(refreshTelemetry, 5000);

		// Apply the persisted accent theme back on load.
		applyAccentTheme(getStoredAccentTheme());
	});

	onDestroy(() => {
		clearInterval(pollInterval);
	});
</script>

<svelte:window on:click={handleWindowClick} />

<div
	class="flex items-center justify-between w-full px-1.5 md:px-2 h-9 text-xs text-gray-600 dark:text-gray-400 select-none"
>
	<!-- Work mode -->
	<div class="flex items-center min-w-0">
		<div class="flex items-center gap-1.5 px-1.5">
			<div
				class="size-1.5 rounded-full flex-none {workModeActive
					? 'bg-emerald-500 dark:bg-emerald-400'
					: 'bg-gray-400 dark:bg-gray-600'}"
				title={workModeActive ? $i18n.t('Active') : $i18n.t('Inactive')}
			></div>
			<span class="font-medium truncate max-w-[12rem] md:max-w-[22rem]" title={workMode}>
				{workMode}
			</span>
		</div>
	</div>

	<!-- Theme controls + telemetry -->
	<div class="flex items-center gap-0.5">
		<Tooltip content={isDark ? $i18n.t('Switch to light theme') : $i18n.t('Switch to dark theme')}>
			<button
				class="flex cursor-pointer p-1.5 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-850 transition"
				on:click={toggleTheme}
				aria-label={$i18n.t('Theme')}
			>
				{#if isDark}
					<Sun className="size-4" strokeWidth="1.5" />
				{:else}
					<Moon className="size-4" strokeWidth="1.5" />
				{/if}
			</button>
		</Tooltip>

		<div class="relative" bind:this={accentMenuEl}>
			<Tooltip content={$i18n.t('Accent Color')}>
				<button
					class="flex cursor-pointer p-1.5 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-850 transition {showAccentMenu
						? 'bg-gray-100 dark:bg-gray-850'
						: ''}"
					on:click={toggleAccentMenu}
					aria-label={$i18n.t('Accent Color')}
					aria-expanded={showAccentMenu}
				>
					<Palette className="size-4" strokeWidth="1.5" />
				</button>
			</Tooltip>

			{#if showAccentMenu}
				<div
					class="absolute right-0 top-full mt-1 z-50 min-w-[13rem] max-h-[16rem] overflow-y-auto rounded-lg bg-white dark:bg-gray-850 shadow-lg dark:shadow-xl border border-gray-100 dark:border-gray-800 p-1"
				>
					<div class="px-2 py-1 text-xs font-medium text-gray-500 dark:text-gray-400">
						{$i18n.t('Accent Color')}
					</div>
					<div class="h-px bg-gray-100 dark:bg-gray-800 my-0.5"></div>
					{#each ACCENT_THEMES as t (t.id)}
						<button
							class="flex items-center gap-2 w-full px-2 py-1.5 rounded-md hover:bg-gray-100 dark:hover:bg-gray-800 transition text-left"
							on:click={() => selectAccent(t.id)}
						>
							<div class="flex gap-0.5 flex-none">
								<div
									class="size-2 rounded-full"
									style="background: {t.primary}"
									aria-hidden="true"
								></div>
								<div
									class="size-2 rounded-full"
									style="background: {t.secondary}"
									aria-hidden="true"
								></div>
							</div>
							<span class="truncate flex-1">{t.name}</span>
							{#if selectedAccent === t.id}
								<Check className="size-3 flex-none" strokeWidth="2.5" />
							{/if}
						</button>
					{/each}
				</div>
			{/if}
		</div>

		<div class="hidden sm:flex items-center flex-none pl-1.5">
			<div
				class="flex items-center gap-1 px-1.5 py-0.5 rounded-md bg-gray-50 dark:bg-gray-850 text-gray-600 dark:text-gray-400"
				title={$i18n.t('CPU Utilization')}
			>
				<Cpu className="size-3" strokeWidth="1.5" />
				<span class="tabular-nums">{$i18n.t('CPU')}: {telemetry.cpu_usage ?? '--'}%</span>
			</div>
			<div
				class="flex items-center gap-1 px-1.5 py-0.5 ml-1 rounded-md bg-gray-50 dark:bg-gray-850 text-gray-600 dark:text-gray-400"
				title={$i18n.t('System Memory Usage')}
			>
				<span class="tabular-nums"
					>{$i18n.t('RAM')}: {formatGb(telemetry.ram_used_gb)} / {formatGb(
						telemetry.ram_total_gb
					)} GB</span
				>
			</div>
		</div>
	</div>
</div>

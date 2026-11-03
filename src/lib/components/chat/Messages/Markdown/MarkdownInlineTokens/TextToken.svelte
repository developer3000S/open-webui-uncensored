<script lang="ts">
	export let token: any;
	export let done: any = true;
	$: raw = token?.raw ?? '';
</script>

{#if done}
	{raw}
{:else}
	{#each raw.split(' ') as text}
		<span class="fade-in-token">
			{text}{' '}
		</span>
	{/each}
{/if}

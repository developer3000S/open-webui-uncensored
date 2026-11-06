<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { browser } from '$app/environment';

	import * as THREE from 'three';
	import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
	import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';

	export let src: string = '';
	export let modelType: string = 'gltf';

	let containerRef: HTMLDivElement | null = null;
	let scene: THREE.Scene | null = null;
	let camera: THREE.PerspectiveCamera | null = null;
	let renderer: THREE.WebGLRenderer | null = null;
	let controls: OrbitControls | null = null;
	let model: THREE.Object3D | null = null;
	let raycaster: THREE.Raycaster | null = null;
	let pointer: THREE.Vector2 | null = null;
	let animationMixer: THREE.AnimationMixer | null = null;
	let animationClip: THREE.AnimationClip | null = null;
	let isPlaying = false;

	const init = async () => {
		if (!browser || !containerRef) return;

		scene = new THREE.Scene();
		scene.background = new THREE.Color(0xf0f0f0);
		scene.fog = new THREE.Fog(0xf0f0f0, 10, 50);

		camera = new THREE.PerspectiveCamera(45, containerRef.clientWidth / containerRef.clientHeight, 0.1, 100);
		camera.position.set(5, 5, 5);

		renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
		renderer.setSize(containerRef.clientWidth, containerRef.clientHeight);
		renderer.setPixelRatio(window.devicePixelRatio);
		renderer.shadowMap.enabled = true;
		renderer.shadowMap.type = THREE.PCFSoftShadowMap;

		containerRef.appendChild(renderer.domElement);

		controls = new OrbitControls(camera, renderer.domElement);
		controls.enableDamping = true;
		controls.dampingFactor = 0.05;
		controls.minDistance = 2;
		controls.maxDistance = 50;

		// Lighting
		const ambientLight = new THREE.AmbientLight(0xffffff, 0.6);
		scene.add(ambientLight);

		const dirLight = new THREE.DirectionalLight(0xffffff, 1);
		dirLight.position.set(10, 20, 10);
		dirLight.castShadow = true;
		dirLight.shadow.mapSize.width = 2048;
		dirLight.shadow.mapSize.height = 2048;
		scene.add(dirLight);

		const fillLight = new THREE.DirectionalLight(0xffffff, 0.4);
		fillLight.position.set(-10, 0, -10);
		scene.add(fillLight);

		// Grid
		const gridHelper = new THREE.GridHelper(50, 50, 0x444444, 0x888888);
		scene.add(gridHelper);

		raycaster = new THREE.Raycaster();
		pointer = new THREE.Vector2();

		if (src) {
			await loadModel(src, modelType);
		}

		animate();
	};

	const loadModel = async (url: string, type: string) => {
		if (!scene || !camera) return;

		// Remove existing model
		if (model) {
			scene.remove(model);
			model.traverse((child: THREE.Object3D) => {
				if ((child as THREE.Mesh).isMesh) {
					const mesh = child as THREE.Mesh;
					if (mesh.geometry) mesh.geometry.dispose();
					if (mesh.material) {
						if (Array.isArray(mesh.material)) {
							mesh.material.forEach((mat) => mat.dispose());
						} else {
							mesh.material.dispose();
						}
					}
				}
			});
			model = null;
		}

		if (animationMixer) {
			animationMixer.stopAllAction();
			animationMixer = null;
		}

		let loader: any;
		if (type.toLowerCase() === 'gltf' || type.toLowerCase() === 'glb') {
			loader = new GLTFLoader();
		} else {
			// For other formats, try GLTFLoader as fallback or show error
			console.warn(`Format ${type} not supported yet, trying GLTFLoader`);
			loader = new GLTFLoader();
		}

		try {
			const result = await loader.loadAsync(url);

			if (type.toLowerCase() === 'gltf' || type.toLowerCase() === 'glb') {
				model = result.scene;
				if (result.animations && result.animations.length > 0) {
					animationMixer = new THREE.AnimationMixer(result.scene);
					animationClip = result.animations[0];
				}
			} else {
				model = result as unknown as THREE.Object3D;
			}

			if (model) {
				// Center and scale model
				const box = new THREE.Box3().setFromObject(model);
				const center = box.getCenter(new THREE.Vector3());
				const size = box.getSize(new THREE.Vector3());
				const maxDim = Math.max(size.x, size.y, size.z);
				const scale = 2 / maxDim;

				model.position.sub(center.multiplyScalar(scale));
				model.position.y += size.y * scale / 2;
				model.scale.set(scale, scale, scale);

				model.traverse((child: THREE.Object3D) => {
					if ((child as THREE.Mesh).isMesh) {
						const mesh = child as THREE.Mesh;
						mesh.castShadow = true;
						mesh.receiveShadow = true;
					}
				});

				scene.add(model);

				// Position camera to fit model
				const distance = maxDim * scale * 2;
				camera.position.set(distance * 0.5, distance * 0.5, distance);
				controls?.update();
			}
		} catch (e) {
			console.error('Failed to load 3D model:', e);
		}
	};

	const animate = () => {
		if (!renderer || !scene || !camera) return;

		const delta = 0.016;

		if (animationMixer && animationClip && isPlaying) {
			animationMixer.update(delta);
		}

		controls?.update();
		renderer.render(scene, camera);

		requestAnimationFrame(animate);
	};

	const toggleAnimation = () => {
		isPlaying = !isPlaying;
		if (animationMixer && animationClip) {
			if (isPlaying) {
				animationMixer.clipAction(animationClip).play();
			} else {
				animationMixer.stopAllAction();
			}
		}
	};

	const resetCamera = () => {
		if (!model || !camera || !controls) return;

		const box = new THREE.Box3().setFromObject(model);
		const size = box.getSize(new THREE.Vector3());
		const maxDim = Math.max(size.x, size.y, size.z);
		const distance = maxDim * 2;

		camera.position.set(distance * 0.5, distance * 0.5, distance);
		controls?.update();
	};

	onMount(() => {
		init();
	});

	onDestroy(() => {
		if (animationMixer) {
			animationMixer.stopAllAction();
			animationMixer = null;
		}
		if (renderer) {
			renderer.dispose();
			if (containerRef) {
				containerRef.removeChild(renderer.domElement);
			}
			renderer = null;
		}
		if (model) {
			model.traverse((child: THREE.Object3D) => {
				if ((child as THREE.Mesh).isMesh) {
					const mesh = child as THREE.Mesh;
					if (mesh.geometry) mesh.geometry.dispose();
					if (mesh.material) {
						if (Array.isArray(mesh.material)) {
							mesh.material.forEach((mat) => mat.dispose());
						} else {
							mesh.material.dispose();
						}
					}
				}
			});
		}
	});
</script>

<div
	bind:this={containerRef}
	class="w-full h-full bg-gray-100 dark:bg-gray-900 relative overflow-hidden flex items-center justify-center"
>
	{#if !src}
		<div class="flex flex-col items-center justify-center h-full text-gray-500 dark:text-gray-400">
			<svg class="w-16 h-16 mb-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
				<path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M19.428 15.428a2 2 0 00-1.022-.547l-2.387-.477a6 6 0 00-3.86.517l-.318.158a6 6 0 01-3.86.517L6.05 15.21a2 2 0 00-1.806.547M8 4h8l-1 1v5.172a2 2 0 00.586 1.414l5 5c1.26 1.26.367 3.414-1.415 3.414H4.828c-1.782 0-2.674-2.154-1.414-3.414l5-5A2 2 0 009 10.172V5L8 4z" />
			</svg>
			<p class="text-sm font-medium">No 3D model loaded</p>
		</div>
	{:else}
		<div class="absolute top-4 right-4 flex flex-col gap-2 z-20">
			<button
				on:click={resetCamera}
				class="p-2 bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg text-gray-600 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700 transition shadow-sm"
				aria-label="Reset camera"
			>
				<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
					<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
				</svg>
			</button>
			{#if animationClip}
				<button
					on:click={toggleAnimation}
					class={`p-2 rounded-lg text-gray-600 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700 transition shadow-sm ${
						isPlaying ? 'bg-blue-50 dark:bg-blue-900/20 text-blue-600 dark:text-blue-400' : 'bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700'
					}`}
					aria-label={isPlaying ? 'Pause animation' : 'Play animation'}
				>
					<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
						{#if isPlaying}
							<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10 9v6m4-6v6m7-3a9 9 0 11-18 0 9 9 0 0118 0z" />
						{:else}
							<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z" />
							<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
						{/if}
					</svg>
				</button>
			{/if}
		</div>

		<div class="absolute bottom-4 left-4 z-20 text-xs text-gray-500 dark:text-gray-400 bg-white dark:bg-gray-800/80 backdrop-blur px-2 py-1 rounded border border-gray-200 dark:border-gray-700">
			{modelType.toUpperCase()} 3D Model
		</div>
	{/if}
</div>

<style>
	:global(canvas) {
		touch-action: none;
	}
</style>

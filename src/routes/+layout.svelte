<script>
    import { io } from 'socket.io-client';
    import { spring } from 'svelte/motion';
    import { createPyodideWorker } from '$lib/pyodide/createPyodideWorker';
    import { Toaster, toast } from 'svelte-sonner';

    let loadingProgress = spring(0, {
        stiffness: 0.05
    });

    import { onMount, tick, setContext, onDestroy } from 'svelte';
    import {
        config,
        user,
        settings,
        theme,
        WEBUI_NAME,
        WEBUI_VERSION,
        WEBUI_DEPLOYMENT_ID,
        mobile,
        socket,
        socketConnected,
        chatId,
        chats,
        currentChatPage,
        tags,
        temporaryChatEnabled,
        isLastActiveTab,
        isApp,
        appInfo,
        models,
        appData,
        toolServers,
        playingNotificationSound,
        channels,
        channelId,
        terminalServers,
        showControls,
        showFileNavPath,
        showFileNavDir,
        pyodideWorker,
        desktopEvent
    } from '$lib/stores';
    import { getFileContentById } from '$lib/apis/files';
    import { goto } from '$app/navigation';
    import { page } from '$app/stores';
    import { beforeNavigate } from '$app/navigation';
    import { updated } from '$app/state';

    import i18n, { initI18n, getLanguages, changeLanguage } from '$lib/i18n';

    import '../tailwind.css';
    import '../app.css';
    import 'tippy.js/dist/tippy.css';

    import { executeToolServer, getBackendConfig, getModels, getVersion } from '$lib/apis';
    import { getSessionUser, updateUserTimezone, userSignOut } from '$lib/apis/auths';
    import { getAllTags, getChatList } from '$lib/apis/chats';
    import { chatCompletion } from '$lib/apis/openai';
    import {
        addOpenAIConnection,
        removeOpenAIConnection,
        addTerminalConnection,
        removeTerminalConnection
    } from '$lib/utils/connections';

    import { WEBUI_API_BASE_URL, WEBUI_BASE_URL, WEBUI_HOSTNAME } from '$lib/constants';
    import {
        bestMatchingLanguage,
        cleanText,
        displayFileHandler,
        getUserTimezone,
        removeAllDetails
    } from '$lib/utils';
    import { setTextScale } from '$lib/utils/text-scale';

    import NotificationToast from '$lib/components/NotificationToast.svelte';
    import AppSidebar from '$lib/components/app/AppSidebar.svelte';
    import SyncStatsModal from '$lib/components/chat/Settings/SyncStatsModal.svelte';
    import Spinner from '$lib/components/common/Spinner.svelte';
    import { getOutputText } from '$lib/components/chat/Messages/structuredOutput';
    import { getUserSettings } from '$lib/apis/users';
    import dayjs from 'dayjs';
    import { getChannels } from '$lib/apis/channels';

    export let data;

    const unregisterServiceWorkers = async () => {
        if ('serviceWorker' in navigator) {
            try {
                const registrations = await navigator.serviceWorker.getRegistrations();
                await Promise.all(registrations.map((r) => r.unregister()));
                return true;
            } catch (error) {
                console.error('Error unregistering service workers:', error);
                return false;
            }
        }
        return false;
    };

    // handle frontend updates (https://svelte.dev/docs/kit/configuration#version)
    beforeNavigate(async ({ willUnload, to }) => {
        if (updated.current && !willUnload && to?.url) {
            await unregisterServiceWorkers();
            location.href = to.url.href;
        }
    });

    setContext('i18n', i18n);

    const bc = new BroadcastChannel('active-tab-channel');

    let loaded = false;
    let tokenTimer = null;
    let isAuthRedirectInProgress = false;

    let showRefresh = false;

    let showSyncStatsModal = false;
    let syncStatsEventData = null;

    let heartbeatInterval = null;
    let disconnectToastTimer = null;
    let disconnectWarningShown = false;

    const BREAKPOINT = 768;
    const DISCONNECT_TOAST_DELAY_MS = 2000;

    const setupSocket = async (enableWebsocket) => {
        const _socket = io(`${WEBUI_BASE_URL}` || undefined, {
            reconnection: true,
            reconnectionDelay: 1000,
            reconnectionDelayMax: 5000,
            randomizationFactor: 0.5,
            path: '/ws/socket.io',
            transports: enableWebsocket ? ['websocket'] : ['polling', 'websocket'],
            auth: { token: localStorage.token }
        });
        await socket.set(_socket);

        _socket.on('connect_error', (err) => {
            console.log('connect_error', err);
        });

        let hasConnectedOnce = false;

        _socket.on('connect', async () => {
            console.log('connected', _socket.id);

            // Cancel any pending disconnect toast if we reconnected quickly
            if (disconnectToastTimer) {
                clearTimeout(disconnectToastTimer);
                disconnectToastTimer = null;
            }

            if (hasConnectedOnce) {
                socketConnected.set(true);
                // Only show "Reconnected" if the user actually saw the disconnect warning
                if (disconnectWarningShown) {
                    toast.success($i18n.t('Reconnected'));
                    disconnectWarningShown = false;
                }
            }
            hasConnectedOnce = true;

            const res = await getVersion(localStorage.token);

            const deploymentId = res?.deployment_id ?? null;
            const version = res?.version ?? null;

            if (version !== null || deploymentId !== null) {
                if (
                    ($WEBUI_VERSION !== null && version !== $WEBUI_VERSION) ||
                    ($WEBUI_DEPLOYMENT_ID !== null && deploymentId !== $WEBUI_DEPLOYMENT_ID)
                ) {
                    await unregisterServiceWorkers();
                    location.href = location.href;
                    return;
                }
            }

            // Send heartbeat every 30 seconds
            heartbeatInterval = setInterval(() => {
                if (_socket.connected) {
                    console.log('Sending heartbeat');
                    _socket.emit('heartbeat', {});
                }
            }, 30000);

            if (deploymentId !== null) {
                WEBUI_DEPLOYMENT_ID.set(deploymentId);
            }

            if (version !== null) {
                WEBUI_VERSION.set(version);
                window.WEBUI_VERSION = version;
            }

            console.log('version', version);

            if (localStorage.getItem('token')) {
                // Emit user-join event with auth token
                _socket.emit('user-join', { auth: { token: localStorage.token } });
            } else {
                console.warn('No token found in localStorage, user-join event not emitted');
            }
        });

        _socket.on('reconnect_attempt', (attempt) => {
            console.log('reconnect_attempt', attempt);
        });

        _socket.on('reconnect_failed', () => {
            console.log('reconnect_failed');
        });

        _socket.on('disconnect', (reason, details) => {
            console.log(`Socket ${_socket.id} disconnected due to ${reason}`);
            socketConnected.set(false);

            // Delay showing the disconnect toast so brief interruptions
            // (e.g. mobile tab backgrounding) don't flash a nuisance warning
            if (disconnectToastTimer) {
                clearTimeout(disconnectToastTimer);
            }
            disconnectWarningShown = false;
            disconnectToastTimer = setTimeout(() => {
                disconnectToastTimer = null;
                disconnectWarningShown = true;
                toast.warning($i18n.t('Connection lost. Reconnecting...'));
            }, DISCONNECT_TOAST_DELAY_MS);

            if (heartbeatInterval) {
                clearInterval(heartbeatInterval);
                heartbeatInterval = null;
            }

            if (details) {
                console.log('Additional details:', details);
            }
        });
    };

    /**
     * Get or create the persistent Pyodide worker.
     * The worker persists across executions so the virtual FS (IDBFS) is preserved.
     */
    const getOrCreateWorker = () => {
        let worker = $pyodideWorker;
        if (!worker) {
            worker = createPyodideWorker();
            pyodideWorker.set(worker);
        }
        return worker;
    };

    const executePythonAsWorker = async (id, code, cb, files = []) => {
        let result = null;
        let stdout = null;
        let stderr = null;

        let executing = true;
        let packages = [
            /import\s+requests\b|\bfrom\s+requests\b/.test(code) ? 'requests' : null,
            /import\s+bs4\b|\bfrom\s+bs4\b/.test(code) ? 'beautifulsoup4' : null,
            /import\s+numpy\b|\bfrom\s+numpy\b/.test(code) ? 'numpy' : null,
            /import\s+pandas\b|\bfrom\s+pandas\b/.test(code) ? 'pandas' : null,
            /import\s+matplotlib\b|\bfrom\s+matplotlib\b/.test(code) ? 'matplotlib' : null,
            /import\s+seaborn\b|\bfrom\s+seaborn\b/.test(code) ? 'seaborn' : null,
            /import\s+sklearn\b|\bfrom\s+sklearn\b/.test(code) ? 'scikit-learn' : null,
            /import\s+scipy\b|\bfrom\s+scipy\b/.test(code) ? 'scipy' : null,
            /import\s+re\b|\bfrom\s+re\b/.test(code) ? 'regex' : null,
            /import\s+seaborn\b|\bfrom\s+seaborn\b/.test(code) ? 'seaborn' : null,
            /import\s+sympy\b|\bfrom\s+sympy\b/.test(code) ? 'sympy' : null,
            /import\s+tiktoken\b|\bfrom\s+tiktoken\b/.test(code) ? 'tiktoken' : null,
            /import\s+pytz\b|\bfrom\s+pytz\b/.test(code) ? 'pytz' : null
        ].filter(Boolean);

        const worker = getOrCreateWorker();

        // Fetch file content from the server and prepare for the worker
        let filePayloads = [];
        if (files && files.length > 0) {
            for (const file of files) {
                try {
                    const fileId = file?.id;
                    const fileName = file?.filename || file?.name || 'file';
                    if (fileId) {
                        const content = await getFileContentById(fileId);
                        if (content) {
                            filePayloads.push({ name: fileName, data: content });
                        }
                    }
                } catch (e) {
                    console.error('Failed to fetch file for Pyodide:', e);
                }
            }
        }

        worker.postMessage({
            type: 'execute',
            id: id,
            code: code,
            packages: packages,
            files: filePayloads.length > 0 ? filePayloads : undefined
        });

        // Timeout for this specific execution (not the worker itself)
        let timeoutId = setTimeout(() => {
            if (executing) {
                executing = false;
                stderr = 'Execution Time Limit Exceeded';

                // Terminate and recreate the worker on timeout
                worker.terminate();
                pyodideWorker.set(null);

                if (cb) {
                    cb(
                        JSON.parse(
                            JSON.stringify(
                                {
                                    stdout: stdout,
                                    stderr: stderr,
                                    result: result
                                },
                                (_key, value) => (typeof value === 'bigint' ? value.toString() : value)
                            )
                        )
                    );
                }
            }
        }, 60000);

        // Use addEventListener so multiple concurrent executions don't clobber each other
        const onMessage = (event) => {
            const { id: eventId, ...data } = event.data;
            // Only handle responses for this execution ID
            if (eventId !== id) return;
            // Ignore FS responses (they use a type field)
            if (data.type && data.type.startsWith('fs:')) return;

            console.log('pyodideWorker.onmessage', event);
            clearTimeout(timeoutId);
            worker.removeEventListener('message', onMessage);
            worker.removeEventListener('error', onError);

            data['stdout'] && (stdout = data['stdout']);
            data['stderr'] && (stderr = data['stderr']);
            data['result'] && (result = data['result']);

            if (cb) {
                cb(
                    JSON.parse(
                        JSON.stringify(
                            {
                                stdout: stdout,
                                stderr: stderr,
                                result: result
                            },
                            (_key, value) => (typeof value === 'bigint' ? value.toString() : value)
                        )
                    )
                );
            }

            executing = false;
        };

        const onError = (event) => {
            console.log('pyodideWorker.onerror', event);
            clearTimeout(timeoutId);
            worker.removeEventListener('message', onMessage);
            worker.removeEventListener('error', onError);

            if (cb) {
                cb(
                    JSON.parse(
                        JSON.stringify(
                            {
                                stdout: stdout,
                                stderr: stderr,
                                result: result
                            },
                            (_key, value) => (typeof value === 'bigint' ? value.toString() : value)
                        )
                    )
                );
            }
            executing = false;
        };

        worker.addEventListener('message', onMessage);
        worker.addEventListener('error', onError);
    };

    const resolveToolServer = (serverUrl) => {
        let toolServer = $settings?.toolServers?.find((server) => server.url === serverUrl);
        if (!toolServer) {
            const terminalServer = ($settings?.terminalServers ?? []).find(
                (server) => server.url === serverUrl
            );
            if (terminalServer) {
                toolServer = {
                    url: terminalServer.url,
                    auth_type: terminalServer.auth_type ?? 'bearer',
                    key: terminalServer.key ?? '',
                    path: terminalServer.path ?? '/openapi.json'
                };
            }
        }

        let toolServerData =
            $toolServers?.find((server) => server.url === serverUrl) ??
            $terminalServers?.find((server) => server.url === serverUrl);

        let token = null;
        if (toolServer) {
            const auth_type = toolServer?.auth_type ?? 'bearer';
            if (auth_type === 'bearer') token = toolServer?.key;
            else if (auth_type === 'session') token = localStorage.token;
        }

        return { toolServer, toolServerData, token };
    };

    const executeTool = async (data, cb, chatId) => {
        const { toolServer, toolServerData, token } = resolveToolServer(data.server?.url);

        console.log('executeTool', data, toolServer);

        if (toolServer) {
            const res = await executeToolServer(
                token,
                toolServer.url,
                data?.name,
                data?.params,
                toolServerData,
                chatId
            );

            console.log('executeToolServer', res);

            if (data?.name === 'display_file' && data?.params?.path) {
                if (res?.['exists'] !== false) {
                    displayFileHandler(data.params.path, { showControls, showFileNavPath });
                }
            }

            if (['write_file'].includes(data?.name) && data?.params?.path) {
                showFileNavDir.set(res?.['path'] ?? data.params.path);
            }

            if (cb) {
                cb(structuredClone(res));
            }
        } else {
            if (cb) {
                cb({ error: 'Tool Server Not Found' });
            }
        }
    };

    const chatEventHandler = async (event, cb) => {
        const chat = window.location.pathname.includes(`/c/${event.chat_id}`);

        // Skip events from temporary chats that are not the current chat.
        // This prevents notifications from being sent to other tabs/devices
        // for privacy, since temporary chats are not meant to be persisted or visible elsewhere.
        const isTemporaryChat = event.chat_id?.startsWith('local:');
        if (isTemporaryChat && event.chat_id !== $chatId) {
            return;
        }

        let isInBackground = document.visibilityState !== 'visible';
        if (window.electronAPI) {
            const res = await window.electronAPI.send({
                type: 'window:isFocused'
            });
            if (res) {
                isInBackground = !res.isFocused;
            }
        }

        await tick();
        const type = event?.data?.type ?? null;
        const data = event?.data?.data ?? null;

        // Calendar alerts are not chat-scoped, handle before chat_id checks
        if (type === 'calendar:alert' && data) {
            const timeStr =
                data.minutes_until <= 0
                    ? $i18n.t('Starting now')
                    : data.minutes_until === 1
                        ? $i18n.t('Starting in 1 minute')
                        : $i18n.t('Starting in {{count}} minutes', { count: data.minutes_until });

            toast.custom(NotificationToast, {
                componentProps: {
                    onClick: () => {
                        goto('/calendar');
                    },
                    title: data.title,
                    content: timeStr
                },
                duration: 30000,
                unstyled: true
            });

            if ($isLastActiveTab) {
                if ($settings?.notificationEnabled ?? false) {
                    new Notification(`${data.title} • Open WebUI`, {
                        body: timeStr,
                        icon: `${WEBUI_BASE_URL}/static/favicon.png`
                    });
                }
            }
            return;
        }

        // Session-targeted RPC calls (code execution, tool calls, direct completion)
        // must ALWAYS be processed regardless of active chat or tab visibility,
        // because the backend's sio.call blocks waiting for our callback response.
        if (data?.session_id === $socket.id) {
            if (type === 'execute:python') {
                console.log('execute:python', data);
                executePythonAsWorker(data.id, data.code, cb, data.files || []);
                return;
            } else if (type === 'execute:tool') {
                console.log('execute:tool', data);
                executeTool(data, cb, event.chat_id);
                return;
            } else if (type === 'request:chat:completion') {
                console.log(data, $socket.id);
                const { session_id, channel, form_data, model } = data;

                try {
                    const directConnections = $settings?.directConnections ?? {};

                    if (directConnections) {
                        const urlIdx = model?.urlIdx;

                        const OPENAI_API_URL = directConnections.OPENAI_API_BASE_URLS[urlIdx];
                        const OPENAI_API_KEY = directConnections.OPENAI_API_KEYS[urlIdx];
                        const API_CONFIG = directConnections.OPENAI_API_CONFIGS[urlIdx];

                        try {
                            if (API_CONFIG?.prefix_id) {
                                const prefixId = API_CONFIG.prefix_id;
                                form_data['model'] = form_data['model'].replace(`${prefixId}.`, ``);
                            }

                            const [res, controller] = await chatCompletion(
                                OPENAI_API_KEY,
                                form_data,
                                OPENAI_API_URL
                            );

                            if (res) {
                                // raise if the response is not ok
                                if (!res.ok) {
                                    throw await res.json();
                                }

                                if (form_data?.stream ?? false) {
                                    cb({
                                        status: true
                                    });
                                    console.log({ status: true });

                                    // res will either be SSE or JSON
                                    const reader = res.body.getReader();
                                    const decoder = new TextDecoder();

                                    const processStream = async () => {
                                        while (true) {
                                            // Read data chunks from the response stream
                                            const { done, value } = await reader.read();
                                            if (done) {
                                                break;
                                            }

                                            // Decode the received chunk
                                            const chunk = decoder.decode(value, { stream: true });

                                            // Process lines within the chunk
                                            const lines = chunk.split('\n').filter((line) => line.trim() !== '');

                                            for (const line of lines) {
                                                console.log(line);
                                                $socket?.emit(channel, line);
                                            }
                                        }
                                    };

                                    // Process the stream in the background
                                    await processStream();
                                } else {
                                    const data = await res.json();
                                    cb(data);
                                }
                            } else {
                                throw new Error('An error occurred while fetching the completion');
                            }
                        } catch (error) {
                            console.error('chatCompletion', error);
                            cb(error);
                        }
                    }
                } catch (error) {
                    console.error('chatCompletion', error);
                    cb(error);
                } finally {
                    $socket.emit(channel, {
                        done: true
                    });
                }
                return;
            }
        }

        if ((event.chat_id !== $chatId && !$temporaryChatEnabled) || isInBackground) {
            if (type === 'chat:completion') {
                const { done, content, output, title } = data;
                const displayTitle = title || $i18n.t('New Chat');
                const contentPreview = cleanText(removeAllDetails(getOutputText(output) || content || ''));

                if (done) {
                    if (
                        ($settings?.notificationSound ?? true) &&
                        ($settings?.notificationSoundAlways ?? false)
                    ) {
                        playingNotificationSound.set(true);

                        const audio = new Audio(`/audio/notification.mp3`);
                        audio.play().finally(() => {
                            // Ensure the global state is reset after the sound finishes
                            playingNotificationSound.set(false);
                        });
                    }

                    if ($isLastActiveTab) {
                        if ($settings?.notificationEnabled ?? false) {
                            new Notification(`${displayTitle} • Open WebUI`, {
                                body: contentPreview,
                                icon: `${WEBUI_BASE_URL}/static/favicon.png`
                            });
                        }
                    }

                    toast.custom(NotificationToast, {
                        componentProps: {
                            onClick: () => {
                                goto(`/c/${event.chat_id}`);
                            },
                            content: contentPreview,
                            title: displayTitle
                        },
                        duration: 15000,
                        unstyled: true
                    });
                }
            } else if (type === 'chat:title') {
                currentChatPage.set(1);
                await chats.set(await getChatList(localStorage.token, $currentChatPage));
            } else if (type === 'chat:tags') {
                tags.set(await getAllTags(localStorage.token));
            }
        }
    };

    const channelEventHandler = async (event) => {
        console.log('channelEventHandler', event);
        if (event.data?.type === 'typing') {
            return;
        }

        // handle channel created event
        if (event.data?.type === 'channel:created') {
            const res = await getChannels(localStorage.token).catch(async (error) => {
                return null;
            });

            if (res) {
                await channels.set(
                    res.sort(
                        (a, b) =>
                            ['', null, 'group', 'dm'].indexOf(a.type) - ['', null, 'group', 'dm'].indexOf(b.type)
                    )
                );
            }

            return;
        }

        // check url path
        const channel = window.location.pathname.includes(`/channels/${event.channel_id}`);

        let isInBackground = document.visibilityState !== 'visible';
        if (window.electronAPI) {
            const res = await window.electronAPI.send({
                type: 'window:isFocused'
            });
            if (res) {
                isInBackground = !res.isFocused;
            }
        }

        if ((!channel || isInBackground) && event?.user?.id !== $user?.id) {
            await tick();
            const type = event?.data?.type ?? null;
            const data = event?.data?.data ?? null;

            if ($channels) {
                if ($channels.find((ch) => ch.id === event.channel_id) && $channelId !== event.channel_id) {
                    channels.set(
                        $channels.map((ch) => {
                            if (ch.id === event.channel_id) {
                                if (type === 'message') {
                                    return {
                                        ...ch,
                                        unread_count: (ch.unread_count ?? 0) + 1,
                                        last_message_at: event.created_at
                                    };
                                }
                            }
                            return ch;
                        })
                    );
                } else {
                    const res = await getChannels(localStorage.token).catch(async (error) => {
                        return null;
                    });

                    if (res) {
                        await channels.set(
                            res.sort(
                                (a, b) =>
                                    ['', null, 'group', 'dm'].indexOf(a.type) -
                                    ['', null, 'group', 'dm'].indexOf(b.type)
                            )
                        );
                    }
                }
            }

            if (type === 'message') {
                const title = `${data?.user?.name}${event?.channel?.type !== 'dm' ? ` (#${event?.channel?.name})` : ''}`;

                if ($isLastActiveTab) {
                    if ($settings?.notificationEnabled ?? false) {
                        new Notification(`${title} • Open WebUI`, {
                            body: data?.content,
                            icon: `${WEBUI_API_BASE_URL}/users/${data?.user?.id}/profile/image`
                        });
                    }
                }

                toast.custom(NotificationToast, {
                    componentProps: {
                        onClick: () => {
                            goto(`/channels/${event.channel_id}`);
                        },
                        content: data?.content,
                        title: `${title}`
                    },
                    duration: 15000,
                    unstyled: true
                });
            }
        }
    };

    const TOKEN_EXPIRY_BUFFER = 60; // seconds
    const resolveFetchUrl = (input) => {
        if (input instanceof Request) {
            return new URL(input.url, window.location.origin);
        }

        return new URL(input, window.location.origin);
    };

    const resolveFetchHeaders = (input, init) => {
        if (init?.headers) {
            return new Headers(init.headers);
        }

        if (input instanceof Request) {
            return input.headers;
        }

        return new Headers();
    };

    const isAuthenticatedBackendFetch = (input, init) => {
        try {
            const requestUrl = resolveFetchUrl(input);
            const backendOrigin = new URL(WEBUI_BASE_URL || '/', window.location.origin).origin;

            return (
                requestUrl.origin === backendOrigin &&
                resolveFetchHeaders(input, init).has('authorization')
            );
        } catch {
            return false;
        }
    };

    const redirectToAuthAfterUnauthorized = () => {
        if (isAuthRedirectInProgress || window.location.pathname === '/auth') {
            return;
        }

        isAuthRedirectInProgress = true;
        user.set(null);
        localStorage.removeItem('token');
        toast.error($i18n.t('Session expired. Please sign in again.'));

        const currentPath = `${window.location.pathname}${window.location.search}`;
        goto(`/auth?redirect=${encodeURIComponent(currentPath)}`).finally(() => {
            isAuthRedirectInProgress = false;
        });
    };

    const isCurrentSessionUnauthorized = async (originalFetch) => {
        return originalFetch(`${WEBUI_API_BASE_URL}/auths/`, {
            method: 'GET',
            headers: {
                'Content-Type': 'application/json',
                Authorization: `Bearer ${localStorage.token}`
            },
            credentials: 'include'
        })
            .then((res) => res.status === 401)
            .catch(() => false);
    };

    const checkTokenExpiry = async () => {
        const exp = $user?.expires_at; // token expiry time in unix timestamp
        const now = Math.floor(Date.now() / 1000); // current time in unix timestamp

        if (!exp) {
            // If no expiry time is set, do nothing
            return;
        }

        if (now >= exp - TOKEN_EXPIRY_BUFFER) {
            const res = await userSignOut();
            user.set(null);
            localStorage.removeItem('token');

            location.href = res?.redirect_url ?? '/auth';
        }
    };

    const desktopEventHandler = async (event) => {
        // Events that don't require auth
        if (event.type === 'page:reload') {
            location.reload();
            return;
        }
        if (event.type === 'page:navigate' && event.data?.path) {
            await goto(event.data.path);
            return;
        }
        if (event.type === 'query' && (event.data?.query || event.data?.files?.length)) {
            desktopEvent.set(event);
            await goto('/');
            return;
        }
        if (event.type === 'call') {
            desktopEvent.set(event);
            await goto('/');
            return;
        }
        if (event.type === 'theme:update' && event.data?.theme) {
            const newTheme = event.data.theme;
            localStorage.setItem('theme', newTheme);
            theme.set(newTheme);

            // Apply theme classes (mirrors logic from chat/Settings/General.svelte)
            const themes = ['dark', 'light', 'oled-dark'];
            let themeToApply =
                newTheme === 'oled-dark' ? 'dark' : newTheme === 'her' ? 'light' : newTheme;
            if (newTheme === 'system') {
                themeToApply = window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
            }
            themes
                .filter((e) => e !== themeToApply)
                .forEach((e) => {
                    e.split(' ').forEach((cls) => document.documentElement.classList.remove(cls));
                });
            themeToApply.split(' ').forEach((cls) => document.documentElement.classList.add(cls));
            return;
        }
        if (event.type === 'models:refresh') {
            const token = localStorage.token;
            if (token) {
                models.set(
                    await getModels(
                        token,
                        $config?.features?.enable_direct_connections
                            ? ($settings?.directConnections ?? null)
                            : null
                    )
                );
            }
            return;
        }
    };

    const init = async () => {
        await initI18n();

        // Set up socket connection
        await setupSocket(true);

        // Set up user
        const token = localStorage.token;
        if (token) {
            const res = await getSessionUser(token);
            if (res) {
                user.set(res);
                await getUserSettings(token).then((settings) => settings && settings.set(settings));
                await getChannels(token).then((channels) => channels && channels.set(channels));
                await getChatList(token).then((chats) => chats && chats.set(chats));
                await getAllTags(token).then((tags) => tags && tags.set(tags));
                await getModels(
                    token,
                    $config?.features?.enable_direct_connections ? ($settings?.directConnections ?? null) : null
                ).then((models) => models && models.set(models));
            }
        }

        // Auto-show SyncStatsModal when opened with ?sync=true (from community)
        if (
            (window.opener ?? false) &&
            new URLSearchParams(window.location.search).get('sync') === 'true' &&
            ($config?.features?.enable_community_sharing ?? false)
        ) {
            showSyncStatsModal = true;
        }

        // Set up event listeners
        window.addEventListener('resize', onResize);
        window.addEventListener('message', windowMessageEventHandler);
        document.addEventListener('touchstart', touchstartHandler);
        document.addEventListener('touchmove', touchmoveHandler);
        document.addEventListener('touchend', touchendHandler);
        document.addEventListener('visibilitychange', handleVisibilityChange);

        // Set up text scale
        setTextScale();

        // Set up mobile detection
        mobile.set(window.innerWidth < BREAKPOINT);

        // Set up theme
        const savedTheme = localStorage.getItem('theme');
        if (savedTheme) {
            theme.set(savedTheme);
        } else {
            const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
            theme.set(prefersDark ? 'dark' : 'light');
        }

        // Set up timezone
        const timezone = getUserTimezone();
        if (timezone) {
            await updateUserTimezone(timezone);
        }

        // Set up token expiry check
        if (token) {
            tokenTimer = setInterval(checkTokenExpiry, 60000);
        }

        // Set up chat event handler
        $socket?.on('chat:event', chatEventHandler);

        // Set up channel event handler
        $socket?.on('channel:event', channelEventHandler);

        // Set up desktop event handler
        window.electronAPI?.addEventListener('message', desktopEventHandler);

        // Set up window focus/blur events
        window.addEventListener('focus', () => {
            if ($socket?.connected) {
                $socket.emit('user-focus');
            }
        });

        window.addEventListener('blur', () => {
            if ($socket?.connected) {
                $socket.emit('user-blur');
            }
        });

        // Set up window close event
        window.addEventListener('beforeunload', async () => {
            if ($socket?.connected) {
                await $socket.emit('user-leave');
            }
        });

        // Set up keyboard shortcuts
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') {
                showControls.set(false);
            }
        });

        loaded = true;
    };

    const onResize = () => {
        mobile.set(window.innerWidth < BREAKPOINT);
    };

    const touchstartHandler = (e) => {
        if (e.touches.length === 1) {
            touchStartX = e.touches[0].clientX;
        }
    };

    const touchmoveHandler = (e) => {
        if (e.touches.length === 1) {
            const touchX = e.touches[0].clientX;
            const diff = touchX - touchStartX;
            if (diff > 5) {
                e.preventDefault();
            }
        }
    };

    const touchendHandler = () => {};

    const handleVisibilityChange = () => {
        if (document.visibilityState === 'visible') {
            if ($socket?.connected) {
                $socket.emit('user-focus');
            }
        } else {
            if ($socket?.connected) {
                $socket.emit('user-blur');
            }
        }
    };

    const windowMessageEventHandler = (event) => {
        if (event.data?.type === 'open-webui:resize') {
            onResize();
        }
    };

    let touchStartX = 0;

    onMount(async () => {
        await init();

        // Auto-show SyncStatsModal when opened with ?sync=true (from community)
        if (
            (window.opener ?? false) &&
            new URLSearchParams(window.location.search).get('sync') === 'true' &&
            ($config?.features?.enable_community_sharing ?? false)
        ) {
            showSyncStatsModal = true;
        }

        // Auto-show refresh indicator if there's a new version
        if ($WEBUI_VERSION && $WEBUI_VERSION !== WEBUI_VERSION) {
            showRefresh = true;
        }

        // Check for token expiry
        if (localStorage.token) {
            await checkTokenExpiry();
        }
    });

    onDestroy(() => {
        bc.close();
    });
</script>

<svelte:head>
    <title>{$WEBUI_NAME}</title>
    <link crossorigin="anonymous" rel="icon" href="{WEBUI_BASE_URL}/static/favicon.png" />

    <meta name="apple-mobile-web-app-title" content={$WEBUI_NAME} />
    <meta name="description" content={$WEBUI_NAME} />
    <link
        rel="search"
        type="application/opensearchdescription+xml"
        title={$WEBUI_NAME}
        href="/opensearch.xml"
        crossorigin="use-credentials"
    />
</svelte:head>

{#if showRefresh}
    <div class=" py-5">
        <Spinner className="size-5" />
    </div>
{/if}

{#if loaded}
    {#if $isApp}
        <div class="flex flex-row h-screen">
            <AppSidebar />

            <div class="w-full flex-1 max-w-[calc(100%-4.5rem)]">
                <slot />
            </div>
        </div>
    {:else}
        <slot />
    {/if}
{/if}

{#if $config?.features.enable_community_sharing}
    <SyncStatsModal bind:show={showSyncStatsModal} eventData={syncStatsEventData} />
{/if}

<Toaster
    theme={$theme.includes('dark')
        ? 'dark'
        : $theme === 'system'
            ? window.matchMedia('(prefers-color-scheme: dark)').matches
                ? 'dark'
                : 'light'
            : 'light'}
    richColors
    position="top-right"
    closeButton
    toastOptions={{ classes: { closeButton: '!bg-white/80 !text-gray-500 !border-gray-200 hover:!bg-gray-50 hover:!text-gray-700 dark:!bg-gray-850 dark:!text-gray-400 dark:!border-gray-700 dark:hover:!bg-gray-800 dark:hover:!text-gray-200' } }} />
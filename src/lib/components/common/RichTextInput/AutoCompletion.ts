import { Extension } from '@tiptap/core';
import { Plugin, PluginKey } from 'prosemirror-state';
import type { EditorView } from '@tiptap/pm/view';

export const AIAutocompletion = Extension.create({
    name: 'aiAutocompletion',

    addOptions() {
        return {
            generateCompletion: (prompt: string) => Promise.resolve(prompt),
            debounceTime: 1000
        };
    },

    addGlobalAttributes() {
        return [
            {
                types: ['paragraph'],
                attributes: {
                    class: {
                        default: null,
                        parseHTML: (element) => element.getAttribute('class'),
                        renderHTML: (attributes) => {
                            if (!attributes.class) return {};
                            return { class: attributes.class };
                        }
                    },
                    'data-prompt': {
                        default: null,
                        parseHTML: (element) => element.getAttribute('data-prompt'),
                        renderHTML: (attributes) => {
                            if (!attributes['data-prompt']) return {};
                            return { 'data-prompt': attributes['data-prompt'] };
                        }
                    },
                    'data-suggestion': {
                        default: null,
                        parseHTML: (element) => element.getAttribute('data-suggestion'),
                        renderHTML: (attributes) => {
                            if (!attributes['data-suggestion']) return {};
                            return { 'data-suggestion': attributes['data-suggestion'] };
                        }
                    }
                }
            }
        ];
    },

    addProseMirrorPlugins() {
        let debounceTimer: ReturnType<typeof setTimeout> | null = null;
        let loading: boolean = false;
        let touchStartX: number = 0;
        let touchStartY: number = 0;
        let isComposing: boolean = false;

        const handleAICompletion = (view: EditorView): void => {
            const { state } = view;
            const { selection } = state;
            const { $head } = selection;

            if (selection.empty && $head.pos === $head.end()) {
                if (this.options.debounceTime !== null) {
                    if (debounceTimer) clearTimeout(debounceTimer);
                    const currentPos = $head.before();

                    debounceTimer = setTimeout(() => {
                        if (isComposing) return;

                        const newState = view.state;
                        const newSelection = newState.selection;
                        const newNode = newState.doc.nodeAt(currentPos);

                        if (
                            newNode &&
                            newNode.type.name === 'paragraph' &&
                            newSelection.$head.pos === newSelection.$head.end() &&
                            newSelection.$head.pos === currentPos + newNode.nodeSize - 1
                        ) {
                            const prompt = newNode.textContent;

                            if (prompt.trim() !== '') {
                                if (loading) return;
                                loading = true;

                                if (typeof this.options.generateCompletion === 'function') {
                                    this.options.generateCompletion(prompt)
                                        .then((suggestion) => {
                                            if (suggestion && suggestion.trim() !== '') {
                                                if (view.state.selection.$head.pos === view.state.selection.$head.end()) {
                                                    if (view.state === newState) {
                                                        view.dispatch(
                                                            newState.tr.setNodeMarkup(currentPos, undefined, {
                                                                ...newNode.attrs,
                                                                class: 'ai-autocompletion',
                                                                'data-prompt': prompt,
                                                                'data-suggestion': suggestion
                                                            })
                                                        );
                                                    }
                                                }
                                            }
                                        })
                                        .catch((error) => {
                                            console.error('Error generating completion:', error);
                                        })
                                        .finally(() => {
                                            loading = false;
                                        });
                                }
                            }
                        }
                    }, this.options.debounceTime);
                }
            }
        };

        return [
            new Plugin({
                key: new PluginKey('aiAutocompletion'),
                props: {
                    handleKeyDown(view: EditorView, event: KeyboardEvent): boolean {
                        const { state, dispatch } = view;
                        const { selection } = state;
                        const { $head } = selection;

                        if ($head.parent.type.name !== 'paragraph') return false;

                        const node = $head.parent;

                        if (event.key === 'Tab') {
                            if (node.attrs['data-suggestion']) {
                                const suggestion = node.attrs['data-suggestion'];
                                dispatch(
                                    state.tr.insertText(suggestion, $head.pos).setNodeMarkup($head.before(), undefined, {
                                        ...node.attrs,
                                        class: null,
                                        'data-prompt': null,
                                        'data-suggestion': null
                                    })
                                );
                                return true;
                            }
                        } else {
                            if (node.attrs['data-suggestion']) {
                                dispatch(
                                    state.tr.setNodeMarkup($head.before(), undefined, {
                                        ...node.attrs,
                                        class: null,
                                        'data-prompt': null,
                                        'data-suggestion': null
                                    })
                                );
                            }
                            handleAICompletion(view);
                        }
                        return false;
                    },
                    handleDOMEvents: {
                        compositionstart: () => {
                            isComposing = true;
                            return false;
                        },
                        compositionend(view: EditorView): boolean {
                            isComposing = false;
                            handleAICompletion(view);
                            return false;
                        },
                        touchstart(view: EditorView, event: TouchEvent): boolean {
                            touchStartX = event.touches[0].clientX;
                            touchStartY = event.touches[0].clientY;
                            return false;
                        },
                        touchend(view: EditorView, event: TouchEvent): boolean {
                            const touchEndX = event.changedTouches[0].clientX;
                            const touchEndY = event.changedTouches[0].clientY;

                            const deltaX = touchEndX - touchStartX;
                            const deltaY = touchEndY - touchStartY;

                            if (Math.abs(deltaX) > Math.abs(deltaY) && deltaX > 50) {
                                const { state, dispatch } = view;
                                const { selection } = state;
                                const { $head } = selection;
                                const node = $head.parent;

                                if (node.type.name === 'paragraph' && node.attrs['data-suggestion']) {
                                    const suggestion = node.attrs['data-suggestion'];
                                    dispatch(
                                        state.tr.insertText(suggestion, $head.pos).setNodeMarkup($head.before(), undefined, {
                                            ...node.attrs,
                                            class: null,
                                            'data-prompt': null,
                                            'data-suggestion': null
                                        })
                                    );
                                    return true;
                                }
                            }
                            return false;
                        },
                        mouseup(view: EditorView, _event: MouseEvent): boolean {
                            const { state, dispatch } = view;
                            const tr = state.tr;

                            state.doc.descendants((node, pos) => {
                                if (node.type.name === 'paragraph' && node.attrs['data-suggestion']) {
                                    tr.setNodeMarkup(pos, undefined, {
                                        ...node.attrs,
                                        class: null,
                                        'data-prompt': null,
                                        'data-suggestion': null
                                    });
                                }
                            });

                            if (tr.docChanged) {
                                dispatch(tr);
                            }
                            if (debounceTimer) clearTimeout(debounceTimer);
                            return false;
                        }
                    }
                }
            })
        ];
    }
});

export default AIAutocompletion;

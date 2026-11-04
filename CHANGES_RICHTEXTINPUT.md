# RichTextInput Component TypeScript Conversion Summary

## Overview
Converted the RichTextInput components from JavaScript to TypeScript and fixed the
remaining type errors in the whole `src/lib/components/common/RichTextInput` area.

## Files Converted and Fixed

### 1. listDragHandlePlugin.ts
- **Original**: `listDragHandlePlugin.js` (removed)
- **Status**: ✅ Converted to TypeScript and used by `RichTextInput.svelte`
- **Changes Made**:
  - Added TypeScript interfaces for plugin options, state, and event handlers
  - Fixed type annotations for all functions and variables
  - Added type guards for ProseMirror node types
  - Fixed type issues with the `pmGetPos` property assignment
  - Added proper type handling for the `normalizeItemForList` function
  - Added type assertions for DOM elements

### 2. AutoCompletion.ts
- **Status**: ✅ TypeScript-compatible, import updated to extensionless path

### 3. commands.ts
- **Status**: ✅ Fixed
- **Changes Made**:
  - Added `Editor` / `Range` imports
  - Added `CommandSuggestionProps` interface for the suggestion command

### 4. suggestions.ts
- **Status**: ✅ Fixed
- **Changes Made**:
  - Imported `TippyInstance` / `GetReferenceClientRect` from `tippy.js`
  - Imported `SuggestionProps` / `SuggestionKeyDownProps` from `@tiptap/suggestion`
  - Added `SuggestionItem` type and annotated `item` callbacks
  - Removed the invalid `i18nType` cast

### 5. Collaboration.ts
- **Status**: ✅ Compiles without errors (no remaining `$lib/stores` resolution issue)

### 6. Image/image.ts
- **Status**: ✅ Fixed
- **Changes Made**:
  - Added `EditorImageFile` type
  - Typed `editor.storage.files` access and the `data` event payload

### 7. FormattingButtons.svelte
- **Status**: ✅ Fixed
- **Changes Made**:
  - Exported the `editor` prop so the parent component can pass it
  - Fixed `shortCodesToEmojis` indexing via a typed store

### 8. RichTextInput.svelte
- **Status**: ✅ All TypeScript errors fixed
- **Changes Made**:
  - Named the previously anonymous `findNextTemplate` and `tryParse` functions
  - Added null guards for `editor`
  - Replaced `state.selection.constructor.near` with `Selection.near`
  - Used `Selection.near` / `Fragment` correctly in paste handlers
  - Replaced invalid `editor.getHTML(slice)` with `getHTMLFromFragment`
  - Fixed Element vs HTMLElement types for the bubble/floating menu elements
  - Typed ProseMirror/table/turndown callbacks
  - Removed the duplicated template block and duplicate DOM ids
  - Fixed `editor.storage.files` assignment typing

### 9. stores/index.ts
- **Status**: ✅ `shortCodesToEmojis` is now typed as `Record<string, string>`

## Verification
- `npx svelte-check --tsconfig ./tsconfig.json` reports **no errors for any file under
  `src/lib/components/common/RichTextInput`**.

## Notes
The repository still contains unrelated pre-existing TypeScript errors in other areas
(e.g. `src/lib/stores/index.ts` duplicate index signatures in `Config`, route pages, etc.).
Those are outside the scope of the RichTextInput conversion.

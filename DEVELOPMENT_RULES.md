# Правила разработки фронтенда (Svelte 5 + Vite/SvelteKit)

Краткий свод правил, чтобы не повторять ошибки, из-за которых падал `npm run build`
(битые shorthand-атрибуты, `{...}` внутри `class=""`, рассогласованные теги, a11y-нарушения).

## 1. Синтаксис Svelte

- **Никогда не вставляйте многострочные JS-выражения внутрь строкового атрибута**
  вида `class="... {cond ? 'a' : 'b'}"` — это ломает парсер (`attribute_empty_shorthand`).
  Используйте шаблонные строки:
  ```svelte
  <!-- ПЛОХО -->
  <button class="px-3 {($settings?.x ?? false) ? '' : 'outline-hidden'}">
  <!-- ХОРОШО -->
  <button class={`px-3 ${$settings?.x ? '' : 'outline-hidden'}`}>
  <!-- ЛУЧШЕ (clsx) -->
  <button class={clsx('px-3', !$settings?.x && 'outline-hidden')}>
  ```
- CSS-декларации (`border-radius: 0.5rem;`) запрещены внутри `class=""` — только Tailwind-классы
  либо `<style>`-блок компонента.
- Кликабельный элемент — это `<button type="button">` или `<a>`, а не `<div on:click>`.
  Не «глушите» a11y-предупреждения через `<!-- svelte-ignore -->`; исправляйте разметку.
- После любого патча проверяйте баланс открывающих/закрывающих тегов и блоков `{#each}…{/each}`.

## 2. Инструментальная проверка (обязательно перед коммитом)

```bash
npm run check            # svelte-check: типы + диагностика компилятора
npx eslint .             # eslint-plugin-svelte (включая правила a11y)
npm run format           # prettier — единое форматирование .svelte
node scripts/svelte-compile-check.mjs src/**/*.svelte   # быстрая проверка компилируемости
```

- `eslint.config.js`: правило `svelte/valid-compile` должно быть `'error'`
  (сейчас отключено — именно поэтому битый `Chat.svelte` дошёл до сборки).
- Предупреждения a11y (`a11y_click_events_have_key_events`,
  `a11y_no_static_element_interactions`) не подавляются `svelte-ignore` без задачи-тикета.

## 3. CI / pre-commit

- В CI должен запускаться **`npm run build`**, а не только lint: ошибка сборки ловится
  на PR, а не на `docker build` (1450 секунд ожидания — неприемлемо).
- Добавить в `.pre-commit-config.yaml` хук `npm run check` (или `lint-staged` + eslint)
  для файлов `src/**/*.svelte`.
- Рабочие workflow `lint-frontend.disabled` / `lint-backend.disabled` включить (убрать `.disabled`).

## 4. Патчи и правки, сгенерированные AI/инструментами

- Любой автопатч `.svelte` проходит через `svelte-check`/компилятор **до** коммита.
- Правки применяются маленькими кусками: один логический блок = один diff;
  после каждой правки — перечитать изменённый фрагмент глазами (баланс тегов/кавычек).
- Ручной smoke-test UI затронутых компонентов (`FilesModal`, `playground/Chat`) после изменений.

## 5. Про «переписать проект на другом стеке»

Не требуется. Ошибки были синтаксическими/гигиеническими, а не архитектурными:
стеки Svelte 5 + Vite + Tailwind полностью поддерживают корректные решения
(`clsx`, `svelte-check`, `eslint-plugin-svelte`). Переход на React/Vue не устранил бы
эти классы ошибок — их устраняет только контроль качества выше (пункты 2–4).

echo "Для переустановки запусти: rm -rf node_modules package-lock.json && npm install"
echo "npm install eslint@10.14.0 jimp@1.6.1 minimatch@11.0.4 tmp@0.2.7 phin@3.7.1 file-type@21.3.4"
echo ""
echo

echo "######################"
echo "Запускаю git pull"
echo "######################"
git pull   # or copy the two edited files: src/routes/+layout.svelte, package.json (+package-lock.json)

echo "######################"
echo "Запускаю npm install"
echo "######################"
npm install            # picks up @internationalized/date
npm update typescript-eslint @typescript-eslint/eslint-plugin @typescript-eslint/parser --latest

echo "########################"
echo "Запускаю npm run check"
echo "########################"
npm run check          # svelte-check — уже есть в package.json, но, видимо, не запускался

echo "########################"
echo "Запускаю npx prettier"
echo "########################"
npx prettier --check "src/**/*.svelte" 

echo "########################"
echo "Запускаю npm run build"
echo "########################"
npm run build          # verify full production build (my final build attempt here was OOM-killed at the bundling stage, exit 137 — close to completion; add NODE_OPTIONS=--max-old-space-size=8192 if you see "Killed")
npm run lint:frontend  # should pass after the typescript-eslint update

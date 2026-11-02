echo "Для переустановки запусти: rm -rf node_modules package-lock.json && npm install"
echo "npm install eslint@10.14.0 jimp@1.6.1 minimatch@11.0.4 tmp@0.2.7 phin@3.7.1 file-type@21.3.4"
echo ""
echo

echo "######################"
echo "Запускаю git pull"
echo "######################"
# git pull
# or copy the two edited files: src/routes/+layout.svelte, package.json (+package-lock.json)

echo "######################"
echo "Запускаю npm install"
echo "######################"
# nvm install 22.23.3                                                                                                                                   root@mac16
# Verify the Node.js version:
node -v # Should print "v22.23.3"
# Verify npm version:
npm -v # Should print "12.2.1".

# npm install # picks up @internationalized/date
# npm install --save-dev typescript-eslint@latest @typescript-eslint/eslint-plugin@latest @typescript-eslint/parser@latest
# npm install vue @vitejs/plugin-vue vite-plugin-singlefile --save-dev

echo "########################"
echo "Запускаю npm run check"
echo "########################"
npm run check # svelte-check — уже есть в package.json, но, видимо, не запускался

echo "########################"
echo "Запускаю npx prettier"
echo "########################"
npx prettier --check "src/**/*.svelte" --write

echo "########################"
echo "Запускаю npm run build"
echo "########################"
npm run build # verify full production build (my final build attempt here was OOM-killed at the bundling stage, exit 137 — close to completion; add NODE_OPTIONS=--max-old-space-size=8192 if you see "Killed")
npm run lint:frontend # should pass after the typescript-eslint update

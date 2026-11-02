echo "Для переустановки запусти: rm -rf node_modules package-lock.json && npm install"
echo "npm install eslint@10.14.0 jimp@1.6.1 minimatch@11.0.4 tmp@0.2.7 phin@3.7.1 file-type@21.3.4"
echo ""
echo

echo "######################"
echo "Запускаю git pull"
echo "######################"

echo "######################" > errors.txt
echo "Запускаю git pull" >> errors.txt
echo "######################" >> errors.txt  
git pull >> errors.txt
# or copy the two edited files: src/routes/+layout.svelte, package.json (+package-lock.json)

echo "######################"
echo "Запускаю npm install"
echo "######################"

echo "######################" >> errors.txt
echo "Запускаю npm install" >> errors.txt
echo "######################" >> errors.txt

nvm install 24                                                                                                                                   root@mac16
# Verify the Node.js version:
node -v # Should print "v24.22.2".
# Verify npm version:
npm -v # Should print "12.2.1".

npm install >> errors.txt
# picks up @internationalized/date
npm update typescript-eslint @typescript-eslint/eslint-plugin @typescript-eslint/parser --latest  >> errors.txt

echo "########################"
echo "Запускаю npm run check"
echo "########################"

echo "########################" >> errors.txt
echo "Запускаю npm run check" >> errors.txt
echo "########################" >> errors.txt
npm run check >> errors.txt
# svelte-check — уже есть в package.json, но, видимо, не запускался

echo "########################"
echo "Запускаю npx prettier"
echo "########################"

echo "########################" >> errors.txt
echo "Запускаю npx prettier" >> errors.txt
echo "########################" >> errors.txt
npx prettier --check "src/**/*.svelte" >> errors.txt 

echo "########################"
echo "Запускаю npm run build"
echo "########################"

echo "########################" >> errors.txt
echo "Запускаю npm run build" >> errors.txt
echo "########################" >> errors.txt
npm run build >> errors.txt
# verify full production build (my final build attempt here was OOM-killed at the bundling stage, exit 137 — close to completion; add NODE_OPTIONS=--max-old-space-size=8192 if you see "Killed")
npm run lint:frontend >> errors.txt
# should pass after the typescript-eslint update

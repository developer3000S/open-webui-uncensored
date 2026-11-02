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
npm run build

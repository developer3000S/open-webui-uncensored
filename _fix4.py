import re, json

f = 'src/lib/components/chat/Chat.svelte'
s = open(f).read()
old = 'const addMessages = ({ modelId, parentId, messages })  => {'
assert old in s, "pattern not found"
s = s.replace(old, 'const addMessages = async ({ modelId, parentId, messages }: any) => {')
open(f, 'w').write(s)
print('Chat.svelte addMessages made async')

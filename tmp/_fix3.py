import re

# Fix Database.svelte: reader.onload = (e: any) { await ... } -> async
f = 'src/lib/components/admin/Settings/Database.svelte'
s = open(f).read()
n1 = s.count('reader.onload = (e: any) {')
s2 = s.replace('reader.onload = (e: any) {', 'reader.onload = async (e: any) => {')
open(f, 'w').write(s2)
print('Database replaced:', n1)

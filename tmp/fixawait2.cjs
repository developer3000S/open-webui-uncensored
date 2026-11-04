const fs=require('fs');
const {parse}=require('svelte/compiler');

function findEnclosing(src,pos){
  // scan backwards from pos, tracking brace depth to find function boundaries
  // candidates: arrow "=>", "function" keyword. Find the nearest one whose body contains pos.
  let i=pos;
  // First walk back to the start of the innermost block containing pos
  let depth=0;
  for(i=pos;i>=0;i--){
    const ch=src[i];
    if(ch==='}'||ch===')'||ch===']')depth++;
    else if(ch==='{'&&depth>0)depth--;
    else if(ch===')'||ch===']'){/*handled*/}
    if(ch==='{'&&depth===0){
      // check preceding text for arrow or function(
      const before=src.slice(Math.max(0,i-400),i);
      const am=before.match(/\)\s*(async\s+)?\([^)]*\)\s*=>$/)||before.match(/=>$/);
      const fm=before.match(/function\s*\w*\s*\([^()]*\)$/)||before.match(/async\s+function\s*\w*\s*\([^()]*\)$/);
      if(am||fm){
        // find start of this arrow/function expression params
        return {bodyStart:i,before};
      }
      // not a function body boundary we can patch; continue scanning further out
    }
  }
  return null;
}

// simpler robust approach: regex all non-async arrow functions & report their param-start and body ranges via brace matching
function listNonAsyncArrows(src){
  const re=/\(([^()]|\([^()]*\))*\)\s*=>/g;
  let m,res=[];
  while((m=re.exec(src))!==null){
    const start=m.index;
    // skip if preceded by 'async '
    const pre=src.slice(Math.max(0,start-7),start);
    if(/\basync\s+$/.test(pre))continue;
    // find body start '{' after =>
    let j=start+m[0].length;
    while(j<src.length&&/\s/.test(src[j]))j++;
    if(src[j]==='{'){
      // brace match
      let d=0,k=j;
      for(;k<src.length;k++){if(src[k]==='{')d++;else if(src[k]==='}'){d--;if(d===0)break;}}
      res.push({start,end:k});
    } else {
      // expression body: end at newline with balanced parens — approximate: until matching close of enclosing construct; use up to next '\n' where depth returns
      res.push({start,end:j+2000,expr:true});
    }
  }
  return res;
}

function fix(file){
  let src=fs.readFileSync(file,'utf8');
  for(let iter=0;iter<30;iter++){
    let err;
    try{parse(src);return true;}catch(e){err=e;}
    if(!/await.*outside an async function/.test(err.message))return false;
    const pos=err.start.character;
    const arrows=listNonAsyncArrows(src).filter(a=>a.start<pos&&a.end>pos);
    if(arrows.length===0)return false;
    const inner=arrows.reduce((a,b)=>b.start>a.start?b:a);
    src=src.slice(0,inner.start)+'async '+src.slice(inner.start);
  }
  return false;
}
for(const f of process.argv.slice(2)){
  console.log((fix(f)?'FIXED ':'FAILED ')+f);
}

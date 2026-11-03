const fs=require('fs');
const {parse}=require('svelte/compiler');

// list non-async arrow functions AND non-async "const name = (...) =>" handled by same regex (they are arrows too)
// problem: params with nested parens default values. Use tolerant param matcher via manual scan.
function listArrows(src){
  const res=[];
  // find every '=>' occurrence, then walk backwards to matching '(' and further to check 'async'
  for(let i=0;i<src.length;i++){
    if(src[i]==='='&&src[i+1]==='>'){
      // walk back over whitespace
      let j=i-1; while(j>=0&&/\s/.test(src[j]))j--;
      if(src[j]!==')')continue;
      // match parens backwards
      let d=0,k=j;
      for(;k>=0;k--){const c=src[k];if(c===')')d++;else if(c==='('){d--;if(d===0)break;}}
      if(k<0)continue;
      const start=k;
      const pre=src.slice(Math.max(0,start-7),start);
      if(/\basync\s+$/.test(pre))continue;
      // body end: after => find first '{' skipping spaces -> brace match; else expression body till newline depth 0
      let b=i+2; while(b<src.length&&/\s/.test(src[b]))b++;
      let end;
      if(src[b]==='{'){let dd=0;for(end=b;end<src.length;end++){if(src[end]==='{')dd++;else if(src[end]==='}'){dd--;if(dd===0)break;}}}
      else{ // expression body: until line where paren depth returns below 0 — approximate to next '\n' followed by non-continuation
        end=Math.min(src.length,i+4000);
      }
      res.push({start,end});
    }
  }
  return res;
}

function fix(file){
  let src=fs.readFileSync(file,'utf8');
  for(let iter=0;iter<60;iter++){
    let err;
    try{parse(src);fs.writeFileSync(file,src);return true;}catch(e){err=e;}
    if(!/await.*outside an async function/.test(err.message))return false;
    const pos=err.start.character;
    const arrows=listArrows(src).filter(a=>a.start<pos&&a.end>pos);
    if(arrows.length===0)return false;
    const inner=arrows.reduce((a,b)=>b.start>a.start?b:a);
    src=src.slice(0,inner.start)+'async '+src.slice(inner.start);
  }
  return false;
}
for(const f of process.argv.slice(2)){console.log((fix(f)?'FIXED ':'FAILED ')+f);}

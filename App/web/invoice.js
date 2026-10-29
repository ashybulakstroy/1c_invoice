'use strict';
/* Invoice panel (Etap 5). Candidates are shown, but only the operator confirms a link.
   Reads the shared page state and helpers from app.js; touches no OCR behavior. */
(function invoicePanel(){
const $ = id => document.getElementById(id);
const INV = {jobId:null, revision:null, model:null, picks:new Map(), busy:false, dirty:false, pdfUrl:null};

function clearPdf(){
  const frame=$('invoice-print-preview');
  frame.hidden=true;frame.removeAttribute('src');
  if(INV.pdfUrl)URL.revokeObjectURL(INV.pdfUrl);
  INV.pdfUrl=null;
}
function markDirty(){
  INV.dirty=true;clearPdf();
  $('invoice-pdf').hidden=true;
  $('invoice-train').disabled=true;
  $('invoice-pdf-hint').textContent='Данные изменены: сохраните счёт или постройте предпросмотр.';
}

function money(value){
  if(value===null||value===undefined||value==='')return '—';
  const number=Number(String(value).replace(/\s+/g,'').replace(/,/g,'.'));
  if(!Number.isFinite(number))return String(value);
  return number.toLocaleString('ru-RU',{minimumFractionDigits:2,maximumFractionDigits:2})+' ₸';
}
function qty(value){
  const number=Number(String(value??'').replace(/,/g,'.'));
  return Number.isFinite(number)?number.toLocaleString('ru-RU',{maximumFractionDigits:9}):'—';
}
function result(){
  try{return state.result||null;}catch(error){return null;}
}
function badge(text,kind){
  const span=node('span','inv-badge '+(kind||''),text);return span;
}

async function fetchModel(){
  try{
    const response=await fetch(`/api/jobs/${INV.jobId}/invoice`);
    return response.ok?await response.json():null;
  }catch(error){return null;}
}

function pickFromRows(model){
  INV.picks=new Map();
  for(const row of model.generation.items){
    if(row.match_status==='manual'||row.match_status==='remembered'||row.match_status==='suggested'){
      INV.picks.set(String(row.row_id),{name:row.name,unit:row.unit||'шт',
        quantity:String(row.quantity||'1'),service:!!row.service,
        catalog_id:row.catalog_id||null,code:row.code||null});
    }
  }
}

function selectionPayload(){
  const selections={};
  for(const [rowId,pick] of INV.picks)selections[String(rowId)]={
    name:pick.name,unit:pick.unit,quantity:pick.quantity,service:!!pick.service,
    catalog_id:pick.catalog_id||null,code:pick.code||null};
  return {selections};
}

function pickLabel(row){
  const pick=INV.picks.get(String(row.row_id));
  if(pick)return pick.name+' · '+pick.unit+' · '+qty(pick.quantity);
  if(row.match_status==='learned')return (row.name||'')+' · обучено';
  if(row.match_status==='suggested')return (row.name||'')+' · предложено';
  return null;
}

function renderRow(item,index){
  const li=node('li','inv-row');
  const head=node('div','inv-row-head');
  const left=node('div','inv-row-title');
  const number=node('span','inv-row-number','#'+(index+1));
  const name=node('button','inv-row-name',item.source_name||'—');
  name.type='button';name.title='Показать строку в чеке';
  name.addEventListener('click',()=>{try{focusRow(Number(item.row_id));}catch(error){}});
  const amount=node('span','inv-row-amount',money(item.source_amount));
  left.append(number,name,amount);
  const chosen=node('div','inv-row-chosen');
  chosen.append(badge(item.match_status==='unmatched'?'не выбрана':item.match_status,
                      item.match_status==='unmatched'?'missing':'ok'));
  const known=pickLabel(item);
  if(known)chosen.append(node('span','inv-row-known',known));
  head.append(left,chosen);

  const body=node('div','inv-row-body');
  const search=node('input','inv-search');
  search.type='search';search.placeholder='Поиск в справочнике 1С (название или код)';
  search.setAttribute('aria-label','Поиск 1С для строки '+(item.source_name||''));
  const list=node('div','inv-options');
  const draw=options=>{list.replaceChildren();for(const option of options.slice(0,10))list.append(optionButton(option));};
  let timer=null;
  search.addEventListener('input',()=>{
    clearTimeout(timer);const query=search.value.trim();
    timer=setTimeout(async()=>{
      if(query.length<2){draw(invCandidates(item));return;}
      try{
        const response=await fetch('/api/catalog-1c?q='+encodeURIComponent(query));
        if(!response.ok)return;
        const data=await response.json();
        const fresh=(data.items||[]).map(entry=>({rowId:item.row_id,sourceQuantity:item.source_quantity,
          origin:'search',code:entry.code,name:entry.name,unit:entry.unit,service:entry.service,
          stock_quantity:entry.stock_quantity,catalog_id:entry.id,score:entry.score}));
        draw(fresh.length?fresh:invCandidates(item));
      }catch(error){/* поиск недоступен — показанные кандидаты остаются */}
    },300);
  });
  body.append(search,list);
  const picked=INV.picks.get(String(item.row_id));
  if(picked)body.append(selectionBar(item,picked));
  draw(invCandidates(item));
  li.append(head,body);
  return li;
}

function selectionBar(item,picked){
  const bar=node('div','inv-selection');
  bar.append(node('span','inv-selection-note','Выбрано'));
  const qtyInput=node('input','inv-qty');
  qtyInput.inputMode='decimal';qtyInput.value=picked.quantity;
  qtyInput.setAttribute('aria-label','Количество в 1С для '+picked.name);
  qtyInput.addEventListener('change',()=>{
    const value=String(qtyInput.value).replace(',','.').trim();
    const number=Number(value);
    if(Number.isFinite(number)&&number>0){picked.quantity=value;markDirty();refresh();}
    else{qtyInput.value=picked.quantity;toast('Количество в 1С должно быть положительным числом');}
  });
  bar.append(node('span','inv-selection-unit',picked.unit),qtyInput);
  const clear=node('button','inv-clear','Сбросить');
  clear.type='button';
  clear.addEventListener('click',()=>{INV.picks.delete(String(item.row_id));markDirty();refresh();});
  bar.append(clear);
  return bar;
}

function optionButton(option){
  const button=node('button','inv-option');
  button.type='button';
  button.append(node('span','inv-option-name',option.name||'—'),
                node('span','inv-option-meta',[
                  option.origin==='proposal'?'в предложениях':option.origin==='remembered'?'подтверждено ранее':'справочник',
                  option.code?'код '+option.code:null,
                  option.unit?option.unit:null,
                  option.stock_quantity!=null?('остаток '+option.stock_quantity):'остаток unknown'
                ].filter(Boolean).join(' · ')));
  button.addEventListener('click',()=>{
    const defaultQuantity=option.service?'1':String(safeQuantity(option));
    INV.picks.set(String(option.rowId),{name:option.name,unit:option.unit||(option.service?'усл':'шт'),
      quantity:defaultQuantity,service:!!option.service,catalog_id:option.catalog_id||option.id||null,
      code:option.code||null});
    markDirty();
    refresh();
  });
  return button;
}

function safeQuantity(item){
  const number=Number(String(item.sourceQuantity??'1').replace(/,/g,'.'));
  return Number.isFinite(number)&&number>0?number:1;
}

function invCandidates(item){
  const data=(INV.model&&INV.model.candidates&&INV.model.candidates[String(item.row_id)])||{};
  const list=[];
  for(const option of data.items||[])list.push({rowId:item.row_id,sourceQuantity:item.source_quantity,origin:'proposal',...option});
  for(const option of data.remembered||[])list.push({rowId:item.row_id,sourceQuantity:item.source_quantity,origin:'remembered',...option});
  return list;
}

function renderDocument(model){
  const host=$('invoice-doc');
  host.replaceChildren();
  const form=model.document.print_form||{};
  const issuer=model.document.issuer||{};
  const heading=node('div','invoice-doc-head');
  heading.append(node('strong','invoice-doc-title',`Счёт ${model.document.number||''}`),
                 node('span','invoice-doc-date',form.date||model.document.date||''));
  const numbers=node('div','invoice-doc-sums');
  const cell=(label,value)=>{const wrap=node('div','invoice-doc-cell');wrap.append(node('span','',label),node('strong','',value));return wrap;};
  numbers.append(cell('Итого',form.total||money(model.document.total)),
                 cell('В том числе НДС',form.vat||'—'),
                 cell('Прописью',form.amount_words||''));
  const supplier=node('p','invoice-doc-supplier',(issuer.name||'')+((issuer.tax_id)?' · БИН '+issuer.tax_id:''));
  host.append(heading,numbers,supplier);
}

function renderBlockers(model){
  const reasons=$('invoice-reasons');
  reasons.replaceChildren();
  for(const reason of model.blocked)reasons.append(node('li','',reason));
  $('invoice-blockers').hidden=!model.blocked.length;
}

function renderPdf(model){
  const link=$('invoice-pdf');
  const hint=$('invoice-pdf-hint');
  if(INV.dirty){
    link.hidden=true;link.removeAttribute('href');
    hint.textContent='Данные изменены: сохраните счёт или постройте предпросмотр.';
  }else if(model.can_render){
    link.hidden=false;
    link.href=INV.pdfUrl||`/api/jobs/${INV.jobId}/invoice.pdf?revision=${encodeURIComponent(model.revision)}&token=${encodeURIComponent(model.token)}`;
    link.download=`invoice-${model.document.number||'preview'}.pdf`;
    hint.textContent='Счёт доступен без подтверждения. Замечания показаны в документе.';
  }else{
    link.hidden=true;link.removeAttribute('href');
    hint.textContent='Скачивание PDF станет доступно после подтверждения всех строк.';
  }
}

function render(){
  const model=INV.model;
  if(!model)return;
  const rows=$('invoice-rows');
  rows.replaceChildren();
  model.generation.items.forEach((item,index)=>rows.append(renderRow(item,index)));
  renderDocument(model);
  renderBlockers(model);
  renderPdf(model);
  const pill=$('invoice-state');
  pill.className='pill '+(model.ready?'done':'processing');
  pill.textContent=model.ready?'Счёт сформирован':'Сформирован · есть замечания';
  $('invoice-empty').hidden=true;$('invoice-content').hidden=false;
}

function refresh(){
  $('invoice-save').disabled=INV.busy;$('invoice-preview').disabled=INV.busy;
  $('invoice-train').disabled=INV.busy||INV.dirty||!INV.model?.ready;
  if(INV.model)render();
}

async function refreshModel(){
  if(INV.busy)return;
  INV.busy=true;
  try{
    const model=await fetchModel();
    if(model&&model.generation){
      INV.model=model;INV.dirty=false;pickFromRows(model);refresh();
      await loadPrintPreview(selectionPayload());
    }
  }finally{INV.busy=false;refresh();}
}

async function loadPrintPreview(payload){
  const jobId=INV.jobId;
  const response=await fetch(`/api/jobs/${jobId}/invoice/preview-pdf`,{
    method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
  if(!response.ok){toast('Не удалось построить печатную форму');return;}
  const blob=await response.blob();
  if(jobId!==INV.jobId)return;
  clearPdf();INV.pdfUrl=URL.createObjectURL(blob);
  const frame=$('invoice-print-preview');
  frame.src=INV.pdfUrl;
  frame.hidden=false;
  frame.setAttribute('tabindex','0');
  frame.scrollIntoView({block:'start',behavior:'instant'});
  frame.focus({preventScroll:true});
}

async function send(action){
  const payload=selectionPayload();
  if(action==='train')payload.confirm=true;
  INV.busy=true;refresh();
  try{
    const response=await fetch(`/api/jobs/${INV.jobId}/invoice/${action}`,{
      method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
    const model=await response.json();
    if(!response.ok){toast(model.error||'Сервер не принял выбор');return;}
    if(action==='train'){
      toast(`Обучение сохранено: ${model.training.remembered} связей`);
      return;
    }
    INV.model=model;
    INV.dirty=false;clearPdf();
    if(action==='selections')pickFromRows(model);
    await loadPrintPreview(payload);
    refresh();
    toast(action==='selections'?'Связи сохранены':'Предпросмотр построен (изменения не сохранены)');
  }catch(error){toast('Счёт недоступен: '+error.message);}
  finally{INV.busy=false;refresh();}
}

function sync(){
  const receipt=result();
  const ok=!!(receipt&&receipt.rows&&receipt.rows.length&&receipt.job_id);
  const panel=$('invoice-panel');
  if(!ok){
    if(panel.hidden&&INV.jobId===null)return;
    panel.hidden=true;INV.jobId=null;INV.model=null;INV.picks=new Map();INV.revision=null;
    return;
  }
  panel.hidden=false;
  const revision=receipt.job_id+':'+receipt.revision;
  if(revision===INV.revision)return;
  INV.jobId=receipt.job_id;INV.revision=revision;
  clearPdf();INV.dirty=false;
  INV.model=null;INV.picks=new Map();
  $('invoice-content').hidden=true;$('invoice-empty').hidden=false;
  refresh();
  refreshModel();
}

function start(){
  $('invoice-save').addEventListener('click',()=>send('selections'));
  $('invoice-preview').addEventListener('click',()=>send('preview'));
  $('invoice-train').addEventListener('click',()=>send('train'));
  setInterval(sync,1200);
}
start();
})();

// Layout only: the separator never changes receipt or invoice data.
(function invoiceDivider(){
  const workspace=document.querySelector('.workspace');
  const panel=document.getElementById('invoice-panel');
  const divider=document.getElementById('invoice-divider');
  const desktop=matchMedia('(min-width:981px)');
  let dragging=false;
  function update(){
    workspace.classList.toggle('invoice-split',!panel.hidden&&desktop.matches);
    const rect=workspace.getBoundingClientRect();
    const height=panel.getBoundingClientRect().top-rect.top;
    divider.setAttribute('aria-valuemin','180');
    divider.setAttribute('aria-valuemax',String(Math.max(180,Math.round(rect.height-180))));
    divider.setAttribute('aria-valuenow',String(Math.round(height)));
  }
  function setHeight(value){
    const max=Math.max(180,workspace.getBoundingClientRect().height-180);
    workspace.style.setProperty('--receipt-panel-height',Math.round(Math.max(180,Math.min(max,value)))+'px');
    update();
  }
  divider.addEventListener('pointerdown',event=>{
    if(event.button!==0||!desktop.matches)return;
    event.preventDefault();dragging=true;
    divider.setPointerCapture(event.pointerId);
    document.body.classList.add('invoice-resizing');
  });
  divider.addEventListener('pointermove',event=>{
    if(dragging)setHeight(event.clientY-workspace.getBoundingClientRect().top);
  });
  function end(){dragging=false;document.body.classList.remove('invoice-resizing');}
  divider.addEventListener('pointerup',end);
  divider.addEventListener('pointercancel',end);
  divider.addEventListener('lostpointercapture',end);
  divider.addEventListener('keydown',event=>{
    if(!['ArrowUp','ArrowDown','Home','End'].includes(event.key))return;
    event.preventDefault();
    const height=panel.getBoundingClientRect().top-workspace.getBoundingClientRect().top;
    setHeight(event.key==='Home'?180:event.key==='End'?Infinity:height+(event.key==='ArrowUp'?-20:20));
  });
  new MutationObserver(update).observe(panel,{attributes:true,attributeFilter:['hidden']});
  window.addEventListener('resize',()=>{
    if(workspace.style.getPropertyValue('--receipt-panel-height')){
      setHeight(parseFloat(workspace.style.getPropertyValue('--receipt-panel-height')));
    }else update();
  });
  desktop.addEventListener('change',update);
  update();
})();

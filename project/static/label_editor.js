'use strict';
const $ = id => document.getElementById(id);
const names = {text:'Текст', field:'Поле Excel', qr:'QR-код', image:'Изображение', line:'Линия'};
let data, model = {name:'Новый шаблон', elements:[]}, currentId = null, selected = -1;
let history = [], future = [], dirty = false, timer, version = 0, previewUrl;
const copy = value => JSON.parse(JSON.stringify(value));
function status(message, error = false) { $('status').textContent = message; $('status').classList.toggle('error', error); }
async function api(url, body) {
  const response = await fetch(url, body === undefined ? {} : {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)});
  if (!response.ok) { const error = await response.json(); throw new Error(error.error || 'Ошибка запроса'); }
  return response;
}
function checkpoint() { history.push(copy(model)); if (history.length > 40) history.shift(); future = []; dirty = true; }
function bound(el, changed) {
  const b = data.body;
  el.width = Math.max(1, Math.min(b.width, Math.round(el.width) || 1));
  el.height = Math.max(1, Math.min(b.height, Math.round(el.height) || 1));
  if (el.type === 'qr') { const side = Math.max(58, Math.min(b.height, changed === 'height' ? el.height : el.width)); el.width = el.height = side; }
  el.x = Math.max(b.x, Math.min(b.x + b.width - el.width, Math.round(el.x) || b.x));
  el.y = Math.max(b.y, Math.min(b.y + b.height - el.height, Math.round(el.y) || b.y));
}
function position(node, el) { Object.assign(node.style, {left:`${el.x / data.width * 100}%`, top:`${el.y / data.height * 100}%`, width:`${el.width / data.width * 100}%`, height:`${el.height / data.height * 100}%`}); }
function draw() {
  $('name').value = model.name;
  $('objects').replaceChildren(); $('layers').replaceChildren();
  model.elements.forEach((el, i) => {
    const node = document.createElement('div'); node.className = 'object' + (i === selected ? ' selected' : ''); position(node, el);
    node.title = names[el.type]; node.dataset.index = i;
    if (i === selected) { const handle = document.createElement('span'); handle.className = 'handle'; node.append(handle); }
    node.addEventListener('pointerdown', event => startDrag(event, i)); $('objects').append(node);
    const button = document.createElement('button'); button.className = 'layer' + (i === selected ? ' selected' : '');
    button.textContent = `${i + 1}. ${names[el.type]}${el.type === 'field' ? ': ' + el.field : el.type === 'text' ? ': ' + el.text : ''}`;
    button.onclick = () => { selected = i; draw(); }; $('layers').append(button);
  });
  const el = model.elements[selected];
  $('empty').hidden = !!el; $('properties').hidden = !el;
  if (el) {
    document.querySelectorAll('[data-prop]').forEach(input => { if (document.activeElement !== input) input.value = el[input.dataset.prop] ?? ''; });
    document.querySelectorAll('[data-kind]').forEach(node => { node.hidden = !node.dataset.kind.split(' ').includes(el.type); });
  }
  $('undo').disabled = !history.length; $('redo').disabled = !future.length;
}
function refresh() { draw(); version++; clearTimeout(timer); timer = setTimeout(preview, 220); }
async function preview() {
  const ticket = version;
  try {
    const response = await api('/api/label-templates/preview', model);
    const blob = await response.blob(); if (ticket !== version) return null;
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    previewUrl = URL.createObjectURL(blob); $('preview').src = previewUrl;
    status(dirty ? 'Есть несохранённые изменения. Для печати сохраните шаблон.' : 'Предпросмотр готов.');
    return blob;
  } catch (error) { if (ticket === version) status(error.message + ' Предпросмотр показывает последний корректный вариант.', true); return null; }
}
function startDrag(event, index) {
  event.preventDefault(); $('paper').focus(); selected = index;
  const resizing = event.target.classList.contains('handle');
  checkpoint(); const original = copy(model.elements[index]); const start = {x:event.clientX,y:event.clientY};
  const rect = $('paper').getBoundingClientRect(); draw();
  const move = e => {
    const dx = Math.round((e.clientX - start.x) * data.width / rect.width), dy = Math.round((e.clientY - start.y) * data.height / rect.height);
    const el = model.elements[index]; Object.assign(el, original);
    if (resizing) { el.width += dx; el.height += dy; } else { el.x += dx; el.y += dy; }
    bound(el); refresh();
  };
  const end = () => { window.removeEventListener('pointermove', move); window.removeEventListener('pointerup', end); window.removeEventListener('pointercancel', end); refresh(); };
  window.addEventListener('pointermove', move); window.addEventListener('pointerup', end); window.addEventListener('pointercancel', end);
}
function add(type, src) {
  if (model.elements.length >= 40) return status('Допустимо не более 40 элементов', true);
  checkpoint();
  const el = {type, x:24, y:76, width:180, height:50, font_size:20, text:'Новый текст', field:data.columns[0] || 'product', prefix:'', align:'left'};
  if (type === 'qr') Object.assign(el, {width:130, height:130, x:245});
  if (type === 'line') Object.assign(el, {width:200,height:2});
  if (type === 'image') Object.assign(el, {width:100,height:100,src});
  model.elements.push(el); selected = model.elements.length - 1; refresh();
}
document.querySelectorAll('[data-add]').forEach(button => { button.onclick = () => add(button.dataset.add); });
document.querySelectorAll('[data-prop]').forEach(input => {
  input.addEventListener('focusout', () => queueMicrotask(draw));
  input.addEventListener('input', () => {
    const el = model.elements[selected]; if (!el) return;
    checkpoint(); const key = input.dataset.prop;
    el[key] = input.type === 'number' ? Math.round(Number(input.value)) : input.value;
    el.font_size = Math.max(10, Math.min(48, el.font_size || 20)); bound(el, key); refresh();
  });
});
$('name').addEventListener('input', () => { checkpoint(); model.name = $('name').value; version++; });
$('add-image').onclick = () => $('image-file').click();
$('image-file').onchange = async () => {
  const file = $('image-file').files[0]; if (!file) return;
  if (file.size > 1_000_000) { status('Выберите PNG/JPEG размером до 1 МБ', true); return; }
  const reader = new FileReader(); reader.onload = () => add('image', reader.result); reader.readAsDataURL(file); $('image-file').value = '';
};
$('delete').onclick = () => { if (selected < 0) return; checkpoint(); model.elements.splice(selected,1); selected = -1; refresh(); };
$('duplicate').onclick = () => { if (selected < 0 || model.elements.length >= 40) return; checkpoint(); const el = copy(model.elements[selected]); el.x += 8; el.y += 8; bound(el); model.elements.push(el); selected = model.elements.length - 1; refresh(); };
function reorder(front) { if (selected < 0) return; checkpoint(); const [el] = model.elements.splice(selected, 1); if (front) model.elements.push(el); else model.elements.unshift(el); selected = front ? model.elements.length - 1 : 0; refresh(); }
$('up').onclick = () => reorder(true); $('down').onclick = () => reorder(false);
$('undo').onclick = () => { if (!history.length) return; future.push(copy(model)); model = history.pop(); selected = -1; dirty = true; refresh(); };
$('redo').onclick = () => { if (!future.length) return; history.push(copy(model)); model = future.pop(); selected = -1; dirty = true; refresh(); };
function canLeave() { return !dirty || window.confirm('Несохранённые изменения будут потеряны. Продолжить?'); }
function openTemplate(id) { currentId = id || null; model = id ? copy(data.templates[id]) : {name:'Новый шаблон',elements:[]}; history = []; future = []; selected = -1; dirty = false; $('templates').value = id || ''; refresh(); }
$('new').onclick = () => { if (canLeave()) openTemplate(null); };
$('templates').onchange = () => { if (canLeave()) openTemplate($('templates').value); else $('templates').value = currentId || ''; };
async function reload() {
  data = await (await api('/api/label-templates')).json();
  $('templates').replaceChildren(new Option('Новый шаблон', ''));
  Object.entries(data.templates).forEach(([id, template]) => $('templates').add(new Option(template.name, id)));
  $('templates').value = currentId || '';
  $('active').textContent = 'Для печати используется: ' + (data.templates[data.active]?.name || 'стандартный шаблон');
  $('columns').replaceChildren(...data.columns.map(column => new Option(column, column)));
  position($('safe-area'), data.body);
}
$('save').onclick = async () => {
  $('save').disabled = true;
  try {
    clearTimeout(timer);
    model.name = $('name').value;
    const revision = version;
    if (!await preview() || revision !== version) return;
    const result = await (await api('/api/label-templates', {...model,id:currentId})).json();
    currentId = result.id; dirty = false; await reload(); status('Шаблон сохранён и используется для печати всех предметов.');
  } catch (error) { status(error.message, true); } finally { $('save').disabled = false; }
};
$('legacy').onclick = async () => { try { await api('/api/label-templates/active',{id:null}); await reload(); status('Включена стандартная печать. Ваши шаблоны сохранены.'); } catch (error) { status(error.message,true); } };
$('download').onclick = async () => { clearTimeout(timer); if (!await preview()) return; const link = document.createElement('a'); link.href = previewUrl; link.download = 'label.png'; link.click(); };
$('paper').addEventListener('keydown', event => {
  if (selected < 0) return;
  const delta = {ArrowLeft:[-1,0],ArrowRight:[1,0],ArrowUp:[0,-1],ArrowDown:[0,1]}[event.key];
  if (delta) { event.preventDefault(); checkpoint(); const el = model.elements[selected]; el.x += delta[0]; el.y += delta[1]; bound(el); refresh(); }
  if (event.key === 'Delete') { event.preventDefault(); $('delete').click(); }
});
window.addEventListener('beforeunload', event => { if (dirty) { event.preventDefault(); event.returnValue = ''; } });
reload().then(() => openTemplate(data.active)).catch(error => { status(error.message, true); document.querySelectorAll('button').forEach(button => { button.disabled = true; }); });

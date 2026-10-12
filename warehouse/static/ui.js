'use strict';

// Table containers use overflow for responsive horizontal scrolling. Moving the
// preview to the document body while it is visible prevents that overflow from
// clipping the image, regardless of its stacking order inside the table.
document.addEventListener('pointerover', event => {
  const cell = event.target.closest('.image-cell, .document-cell');
  if (!cell || cell.contains(event.relatedTarget)) return;
  const preview = cell.querySelector('.image-preview, .document-preview');
  if (!preview || !preview.querySelector('img')) return;

  const placeholder = document.createComment('preview-position');
  preview.before(placeholder);
  document.body.append(preview);
  preview.classList.add('preview-floating');

  const rect = cell.getBoundingClientRect();
  const margin = 10;
  const previewRect = preview.getBoundingClientRect();
  let left = Math.min(rect.left, window.innerWidth - previewRect.width - margin);
  let top = rect.top - previewRect.height - margin;
  if (top < margin) top = Math.min(rect.bottom + margin, window.innerHeight - previewRect.height - margin);
  preview.style.left = `${Math.max(margin, left)}px`;
  preview.style.top = `${Math.max(margin, top)}px`;

  const close = () => {
    preview.classList.remove('preview-floating');
    preview.style.left = '';
    preview.style.top = '';
    placeholder.replaceWith(preview);
    cell.removeEventListener('pointerleave', close);
  };
  cell.addEventListener('pointerleave', close);
});

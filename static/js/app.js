document.addEventListener('click', event => {
  const closeButton = event.target.closest('.flash-close');
  if (closeButton) closeButton.closest('.flash')?.remove();
});

"""Small shared JavaScript helpers, included before page components."""
JS_UTILS = r"""
window.escapeHTML = function(value){
  return String(value == null ? '' : value).replace(/[&<>"']/g, function(c){
    return {'&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'}[c];
  });
};
window.showSimpleToast = function(element, message, isError){
  if(!element)return;
  element.textContent=message;
  element.classList.toggle('err',!!isError);
  element.classList.add('show');
  clearTimeout(element._tm);
  element._tm=setTimeout(function(){element.classList.remove('show');},3200);
};
"""

// 把 <pre><code class="language-mermaid"> 转换为 <div class="mermaid"> 然后触发渲染
(function () {
  // md-to-pdf 通过 marked 把 ```mermaid 渲染成 <code class="language-mermaid">
  document.querySelectorAll('code.language-mermaid').forEach(function (code) {
    var div = document.createElement('div');
    div.className = 'mermaid';
    div.textContent = code.textContent;
    code.parentNode.replaceWith(div);
  });

  mermaid.initialize({
    startOnLoad: false,
    theme: 'default',
    securityLevel: 'loose',
    flowchart: { useMaxWidth: true, htmlLabels: true },
  });

  mermaid.run();
})();

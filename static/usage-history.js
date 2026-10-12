(() => {
  const date=document.getElementById('usage-date'), status=document.getElementById('usage-status');
  const rows=[...document.querySelectorAll('[data-usage-status]')];
  function filter(){
    let count=0;
    rows.forEach(row=>{
      const parsed=new Date(row.dataset.usageTime);
      const day=Number.isNaN(parsed.getTime()) ? '' : new Date(parsed.getTime()+8*3600000).toISOString().slice(0,10);
      row.hidden=Boolean((date.value && day!==date.value)||(status.value && status.value!==row.dataset.usageStatus));
      if(!row.hidden) count++;
    });
    document.getElementById('usage-count').textContent=`当前显示 ${count} 条，共加载 ${rows.length} 条。`;
  }
  document.getElementById('usage-filter').onclick=filter;
  document.getElementById('usage-reset').onclick=()=>{date.value='';status.value='';filter();};
  filter();
})();

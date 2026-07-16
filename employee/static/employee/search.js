$(document).ready(function () {
  $("#employee-search").keyup(function (e) {
    $(".employee-view-type").attr("hx-vals", `{"search":"${$(this).val()}"}`);
  });


  $(".employee-view-type").click(function (e) {
    let view = $(this).attr("data-view");
    var currentURL = window.location.href;
    if (view != undefined){
      if (/\?view=[^&]+/.test(currentURL)) {
        newURL = currentURL.replace(/\?view=[^&]+/, "?view="+view);
      }
      else {
        var separator = currentURL.includes('?') ? '&' : '?';
        newURL = currentURL + separator + "view="+view;
      }
      history.pushState({}, "", newURL);
      $("#employee-search").attr("hx-vals", `{"view":"${view}"}`);
      $('#filterForm').attr("hx-vals", `{"view":"${view}"}`);
      $(".oh-btn--view-active").removeClass("oh-btn--view-active")
      $(this).children("a").addClass("oh-btn--view-active")
    }
  });


  // Active tab script
  function activeProfileTab() {
    var activeTab = localStorage.getItem("activeProfileTab")
    if (!$(activeTab).length && $(`[data-target="#personal_target"]`).length) {
      $(`[data-target="#personal_target"]`)[0].click()
    }else if(activeTab != null){
      $(".oh-general__tab-link--active").removeClass("oh-general__tab-link--active");
      $(`[data-target='${activeTab}']`).addClass("oh-general__tab-link--active");
      $(".oh-general__tab-target").addClass("d-none");
      $(activeTab).removeClass("d-none");
      if($(`[data-target="${activeTab}"]`).length>0){
        $(`[data-target="${activeTab}"]`)[0].click();
      }
    }
  }
  activeProfileTab()
  $("[data-action=general-tab]").on("click",function (e) {
    e.preventDefault();
    const targetId = $(this).attr('data-target');
    localStorage.setItem("activeProfileTab",targetId)
  });

});

function employeeFilter(element) {
  var search = $('#employee-search').val();
  const form = document.querySelector('#filterForm');
  if (!form) return;

  // Sync Select2 (and any widget) values to underlying form fields before collecting
  if (typeof $ !== 'undefined' && $(form).find('select').length) {
    $(form).find('select').each(function () {
      var $sel = $(this);
      if ($sel.data('select2')) {
        var val = $sel.select2('val');
        if (val != null) $sel.val(val);
      }
    });
  }

  // Build params from ALL named controls inside form (querySelectorAll catches hidden dropdown content)
  var params = new URLSearchParams();
  var selector = 'input[name], select[name], textarea[name]';
  var controls = form.querySelectorAll(selector);
  var i, el, j, name, val;
  for (i = 0; i < controls.length; i++) {
    el = controls[i];
    if (!el.name || el.disabled === true) continue;
    name = el.getAttribute('name');
    if (el.tagName === 'SELECT') {
      for (j = 0; j < el.options.length; j++) {
        if (el.options[j].selected) {
          val = el.options[j].value;
          if (val !== undefined && val !== null) params.append(name, val);
        }
      }
    } else if (el.type === 'checkbox' || el.type === 'radio') {
      if (el.checked) params.append(name, el.value !== undefined ? el.value : 'on');
    } else {
      if (el.value !== undefined && el.value !== null) params.append(name, el.value);
    }
  }
  // Also include any controls with form="filterForm" (in case dropdown is ported outside form)
  var byFormId = document.querySelectorAll('input[form="filterForm"][name], select[form="filterForm"][name], textarea[form="filterForm"][name]');
  for (i = 0; i < byFormId.length; i++) {
    el = byFormId[i];
    if (form.contains(el)) continue; // already added
    if (!el.name || el.disabled) continue;
    name = el.getAttribute('name');
    if (el.tagName === 'SELECT') {
      for (j = 0; j < el.options.length; j++) {
        if (el.options[j].selected) params.append(name, el.options[j].value);
      }
    } else if (el.type === 'checkbox' || el.type === 'radio') {
      if (el.checked) params.append(name, el.value !== undefined ? el.value : 'on');
    } else {
      params.append(name, el.value);
    }
  }
  params.set('search', search || '');
  var queryString = params.toString();
  const queryObject = {};
  params.forEach(function (value, key) {
    if (!(key in queryObject)) queryObject[key] = value;
    else if (!Array.isArray(queryObject[key])) queryObject[key] = [queryObject[key], value];
    else queryObject[key].push(value);
  });
  queryObject['search'] = search || '';
  var stringQueyObject = JSON.stringify(queryObject);
  $('#list').attr('hx-vals', stringQueyObject);
  $('#card').attr('hx-vals', stringQueyObject);

  // Use FormData-built URL for the request so all filter fields (including from dropdown) are sent
  if (typeof htmx !== 'undefined') {
    var baseUrl = form.getAttribute('hx-get') || form.getAttribute('data-filter-url') || '';
    if (baseUrl) {
      var url = queryString ? baseUrl + '?' + queryString : baseUrl;
      htmx.ajax('GET', url, {
        target: '#view-container',
        swap: 'innerHTML'
      });
    } else {
      htmx.trigger(form, 'submit');
    }
  }
  if (typeof filterFormSubmit === 'function') {
    filterFormSubmit('filterForm');
  }
}

// Profile picture enlarging

function enlargeImager(image) {
  var enlargeImageContainer = document.getElementById('enlargeImageContainer');
  enlargeImageContainer.innerHTML = '';

  var enlargedImage = document.createElement('img');
  enlargedImage.src = image.src;
  enlargeImageContainer.appendChild(enlargedImage);

  setTimeout(function() {
    enlargeImageContainer.style.display = 'block';
  }, 250);
}

function hideEnlargeImager() {
  var enlargeImageContainer = document.getElementById('enlargeImageContainer');
  enlargeImageContainer.innerHTML = '';
  enlargeImageContainer.style.display = 'none';

}

function toggleColumns(tableId, fieldContainer) {
    // Use :first to ensure we only get the first matching table
    var table = $(`#${tableId}[data-table-name]:first`);
    if (!table.length) {
        return;
    }
    var tableTitle = table.attr("data-table-name");
    var fieldContainerEl = $(`#${fieldContainer}`);
    
    // Clear the container completely before processing
    fieldContainerEl.empty();
    
    let trs = [];
    let seenTitles = new Set(); // Track seen titles to prevent duplicates
    let seenIndexes = new Set(); // Track seen indexes to prevent duplicates
    
    table.find("[data-cell-title]").each(function (indexInArray, valueOfElement) {
        var cellTitle = $(valueOfElement).attr("data-cell-title");
        var cellIndex = $(valueOfElement).attr("data-cell-index");
        
        // Skip if we've already seen this title or index
        if (seenTitles.has(cellTitle) || seenIndexes.has(cellIndex)) {
            return;
        }
        seenTitles.add(cellTitle);
        seenIndexes.add(cellIndex);
        
        trs.push(`
            <li class="oh-dropdown__item oh-sticy-dropdown-item">
                <span>${cellTitle}</span>
                <span class="oh-table__checkbox">
                    <input type="checkbox" name="showTableColumn" onchange="hideCells($(this),'${tableTitle}','${fieldContainer}')" value="${cellIndex}"/>
                </span>
            </li>
         `);
    });

    trsString = "";
    for (let tr = 0; tr < trs.length; tr++) {
        trsString = trsString + trs[tr];
    }

    /* Profile (and similar): column picker is hidden for some users, but localStorage
       may still hold "employee_tab" from a session where the picker existed. Without
       checkboxes we cannot restore visibility — tabs with data-cell-index stay hidden
       while "About" has no index. Show all columns scoped to this table only. */
    if (!fieldContainerEl.length) {
        table.show();
        table.find("[data-cell-index]").show();
        return;
    }

    // Check if buttons already exist to prevent duplicates
    if (!fieldContainerEl.parent().find('.oh-dropdown_btn-header').length) {
        let selectButtons = $(`
        <div class="oh-dropdown_btn-header">
        <button onclick="$(this).parent().parent().find('[type=checkbox]').prop('checked',true).change()" class="oh-btn oh-btn--success-outline">Select All Columns</button>
        <button onclick="$(this).parent().parent().find('[type=checkbox]').prop('checked',false).change()" class="oh-btn oh-btn--primary-outline">Unselect All Columns</button>
        </div>
        `);
        fieldContainerEl.parent().prepend(selectButtons);
    }
    fieldContainerEl.html(trsString);

    var checkboxCount = fieldContainerEl.find("input[type=checkbox]").length;
    if (checkboxCount === 0) {
        table.show();
        table.find("[data-cell-index]").show();
        return;
    }

    var visibleCells = localStorage.getItem(tableTitle);
    if (visibleCells && visibleCells != "[]") {
        table.hide();
        table.find("[data-cell-index]").hide();
    } else {
        table.show();
        table.find("[data-cell-index]").show();
    }

    if (visibleCells) {
        storedIds = JSON.parse(visibleCells);
        fieldContainerEl.find("input[type=checkbox]").prop("checked", false);
        for (let id = 0; id < storedIds.length; id++) {
            const element = storedIds[id];
            fieldContainerEl.find(`input[type=checkbox][value=${element}]`).prop("checked", true);
            hideCells(fieldContainerEl.find(`input[type=checkbox][value=${element}]`), tableTitle, fieldContainer);
        }
        $(`[data-table-name][data-table-name=${tableTitle}]`).show();
    }
}
function hideCells(jqElement, tableTitle, fieldContainer) {
    visibleCells = $(`#${fieldContainer}`).find("input[type=checkbox]:checked");
    let visibleCellsids = [];
    $(`[data-table-name=${tableTitle}] [data-cell-index]`).hide();
    $.each(visibleCells, function (indexInArray, valueOfElement) {
        $(`[data-table-name=${tableTitle}] [data-cell-index=${$(valueOfElement).val()}]`).show();
        visibleCellsids.push($(valueOfElement).val());
    });
    if (jqElement.is(":checked")) {
        var storedIdsSet = new Set(JSON.parse(localStorage.getItem(tableTitle)) || []);
        storedIdsSet.add(jqElement.val());
        var storedIds = Array.from(storedIdsSet);
        localStorage.setItem(tableTitle, JSON.stringify(storedIds));
    } else {
        var storedIds = JSON.parse(localStorage.getItem(tableTitle)) || [];
        var index = storedIds.indexOf(jqElement.val());
        if (index !== -1) {
            storedIds.splice(index, 1);
            localStorage.setItem(tableTitle, JSON.stringify(storedIds));
        }
    }
    $(`[data-table-name=${tableTitle}][data-table-name]`).show();
}

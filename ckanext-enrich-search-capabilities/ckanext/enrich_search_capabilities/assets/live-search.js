ckan.module("enrich-dataset-live-search", function ($) {
  "use strict";

  return {
    options: {
      formId: "dataset-search-form",
      actionUrl: null,
      datasetUrlPattern: null,
      viewAllLabel: "Show all {count} results",
      noResultsLabel: "No datasets match your search.",
      menuLabel: "Dataset suggestions",
      minChars: 2,
      delay: 250,
      limit: 10,
    },

    initialize: function () {
      this.form = $("#" + this.options.formId);
      this.input = this.form.find('input[name="q"]').first();
      if (!this.form.length || !this.input.length) {
        return;
      }

      this.anchor = this.input.closest(".search-input-group");
      if (!this.anchor.length) {
        this.anchor = this.input.parent();
      }
      this.anchor.addClass("enrich-live-search-anchor");

      this.menu = $("<div>", {
        class: "enrich-live-search-menu",
        role: "listbox",
        "aria-label": this.options.menuLabel,
      })
        .prop("hidden", true)
        .appendTo(this.anchor);

      this.timer = null;
      this.request = null;
      this.documentClickHandler = $.proxy(this.onDocumentClick, this);

      this.input.attr({
        "aria-haspopup": "listbox",
        "aria-expanded": "false",
      });
      this.input.on("input", $.proxy(this.onInput, this));
      this.input.on("focus", $.proxy(this.onFocus, this));
      this.input.on("keydown", $.proxy(this.onInputKeydown, this));
      this.menu.on("keydown", $.proxy(this.onMenuKeydown, this));
      this.form.on("submit", $.proxy(this.cancel, this));
      $(document).on("click", this.documentClickHandler);
    },

    teardown: function () {
      $(document).off("click", this.documentClickHandler);
      this.cancel();
    },

    query: function () {
      return this.input.val().trim();
    },

    cancel: function () {
      if (this.timer) {
        clearTimeout(this.timer);
        this.timer = null;
      }
      if (this.request) {
        this.request.abort();
        this.request = null;
      }
      this.closeMenu();
    },

    onInput: function () {
      if (this.timer) {
        clearTimeout(this.timer);
        this.timer = null;
      }

      if (this.query().length < this.options.minChars) {
        this.cancel();
        return;
      }

      this.timer = setTimeout($.proxy(this.search, this), this.options.delay);
    },

    onFocus: function () {
      if (
        this.query().length >= this.options.minChars &&
        this.menu.children().length
      ) {
        this.openMenu();
      }
    },

    search: function () {
      var query = this.query();

      if (this.request) {
        this.request.abort();
      }

      this.request = $.getJSON(this.options.actionUrl, {
        q: query,
        limit: this.options.limit,
      });

      var self = this;
      this.request
        .done(function (response) {
          self.request = null;
          if (!response.success || query !== self.query()) {
            return;
          }
          self.render(response.result);
        })
        .fail(function (xhr, status) {
          self.request = null;
          if (status !== "abort") {
            self.closeMenu();
          }
        });
    },

    render: function (result) {
      this.menu.empty();

      if (!result.items.length) {
        $("<p>", {
          class: "enrich-live-search-empty",
          text: this.options.noResultsLabel,
        }).appendTo(this.menu);
        this.openMenu();
        return;
      }

      var self = this;
      $.each(result.items, function (index, item) {
        var option = $("<a>", {
          class: "enrich-live-search-option",
          role: "option",
          href: self.options.datasetUrlPattern.replace(
            "__name__",
            encodeURIComponent(item.name)
          ),
        }).appendTo(self.menu);

        $("<span>", {
          class: "enrich-live-search-title",
          text: item.title,
        }).appendTo(option);

        if (item.organization) {
          $("<span>", {
            class: "enrich-live-search-meta",
            text: item.organization,
          }).appendTo(option);
        }

        if (item.notes) {
          $("<span>", {
            class: "enrich-live-search-notes",
            text: item.notes,
          }).appendTo(option);
        }
      });

      if (result.count > result.items.length) {
        $("<button>", {
          class: "enrich-live-search-view-all",
          type: "submit",
          text: this.options.viewAllLabel.replace("{count}", result.count),
        }).appendTo(this.menu);
      }

      this.openMenu();
    },

    openMenu: function () {
      this.menu.prop("hidden", false);
      this.input.attr("aria-expanded", "true");
    },

    closeMenu: function () {
      this.menu.prop("hidden", true);
      this.input.attr("aria-expanded", "false");
    },

    focusableItems: function () {
      return this.menu.find(
        ".enrich-live-search-option, .enrich-live-search-view-all"
      );
    },

    onInputKeydown: function (event) {
      if (event.key === "ArrowDown" && !this.menu.prop("hidden")) {
        event.preventDefault();
        this.focusableItems().first().trigger("focus");
      } else if (event.key === "Escape") {
        this.closeMenu();
      }
    },

    onMenuKeydown: function (event) {
      var items = this.focusableItems();
      var currentIndex = items.index(document.activeElement);
      var nextIndex;

      if (event.key === "Escape") {
        event.preventDefault();
        this.closeMenu();
        this.input.trigger("focus");
        return;
      }

      if (event.key === "ArrowDown") {
        nextIndex = (currentIndex + 1) % items.length;
      } else if (event.key === "ArrowUp") {
        nextIndex = (currentIndex - 1 + items.length) % items.length;
      } else {
        return;
      }

      event.preventDefault();
      items.eq(nextIndex).trigger("focus");
    },

    onDocumentClick: function (event) {
      if (!this.anchor[0].contains(event.target)) {
        this.closeMenu();
      }
    },
  };
});

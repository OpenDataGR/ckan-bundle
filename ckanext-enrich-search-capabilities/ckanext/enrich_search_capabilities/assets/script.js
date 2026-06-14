ckan.module("enrich-header-search", function ($) {
  "use strict";

  return {
    initialize: function () {
      this.input = this.el.find('input[name="q"]');
      this.toggle = this.el.find(".enrich-header-search-toggle");
      this.menu = this.el.find(".enrich-header-search-menu");
      this.options = this.menu.find(".enrich-header-search-option");
      this.documentClickHandler = $.proxy(this.onDocumentClick, this);

      this.toggle.on("click", $.proxy(this.toggleMenu, this));
      this.input.on("input", $.proxy(this.onInput, this));
      this.input.on("keydown", $.proxy(this.onInputKeydown, this));
      this.menu.on("keydown", $.proxy(this.onMenuKeydown, this));
      this.menu.on(
        "click",
        "[data-external-url]",
        $.proxy(this.onExternalClick, this)
      );
      $(document).on("click", this.documentClickHandler);

      this.updateQueryLabels();
    },

    teardown: function () {
      $(document).off("click", this.documentClickHandler);
    },

    openMenu: function () {
      this.menu.prop("hidden", false);
      this.el.addClass("is-open");
      this.toggle.attr("aria-expanded", "true");
    },

    closeMenu: function () {
      this.menu.prop("hidden", true);
      this.el.removeClass("is-open");
      this.toggle.attr("aria-expanded", "false");
    },

    toggleMenu: function () {
      if (this.menu.prop("hidden")) {
        this.openMenu();
      } else {
        this.closeMenu();
      }
    },

    onInput: function () {
      this.updateQueryLabels();
      if (this.input.val().trim()) {
        this.openMenu();
      } else {
        this.closeMenu();
      }
    },

    onInputKeydown: function (event) {
      if (event.key === "ArrowDown") {
        event.preventDefault();
        this.openMenu();
        this.options.first().trigger("focus");
      } else if (event.key === "Escape") {
        this.closeMenu();
      }
    },

    onMenuKeydown: function (event) {
      var currentIndex = this.options.index(document.activeElement);
      var nextIndex;

      if (event.key === "Escape") {
        event.preventDefault();
        this.closeMenu();
        this.input.trigger("focus");
        return;
      }

      if (event.key === "ArrowDown") {
        nextIndex = (currentIndex + 1) % this.options.length;
      } else if (event.key === "ArrowUp") {
        nextIndex =
          (currentIndex - 1 + this.options.length) % this.options.length;
      } else {
        return;
      }

      event.preventDefault();
      this.options.eq(nextIndex).trigger("focus");
    },

    onExternalClick: function (event) {
      event.preventDefault();
      var externalUrl = $(event.currentTarget).data("external-url");
      var query = this.input.val().trim();
      var url = query
        ? externalUrl + "?q=" + encodeURIComponent(query)
        : externalUrl;
      window.open(url, "_blank");
      this.closeMenu();
    },

    onDocumentClick: function (event) {
      if (!this.el[0].contains(event.target)) {
        this.closeMenu();
      }
    },

    updateQueryLabels: function () {
      var query = this.input.val().trim();
      this.menu.find(".enrich-header-search-query").text(query);
      this.menu
        .find(".enrich-header-search-query-wrapper")
        .prop("hidden", !query);
    },
  };
});

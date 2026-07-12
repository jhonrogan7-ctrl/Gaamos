// ICONS is loaded from icons.js (included before this script)

const DIET_MAP = {
  VEG:   { cls: 'v',     label: 'V'  },
  VEGAN: { cls: 'vg',    label: 'VG' },
  HALAL: { cls: 'h',     label: 'H'  },
  GF:    { cls: 'gf',    label: 'GF' },
  SPICY: { cls: 'spicy', label: '🌶' },
  RAW:   { cls: 'gf',    label: 'RAW'},
};

function getCookie(name) {
  const m = document.cookie.match('(^|;)\\s*' + name + '\\s*=\\s*([^;]+)');
  return m ? decodeURIComponent(m[2]) : '';
}

document.addEventListener('alpine:init', () => {

  // Lazy-load background images via IntersectionObserver.
  // Usage: <div x-lazy-bg="dish.image_url">
  Alpine.directive('lazy-bg', (el, { expression }, { evaluateLater, effect, cleanup }) => {
    const getUrl = evaluateLater(expression);
    let observer = null;

    effect(() => {
      getUrl(url => {
        // Disconnect previous observer if expression changed
        if (observer) { observer.disconnect(); observer = null; }
        if (!url) { el.style.backgroundImage = ''; return; }

        observer = new IntersectionObserver(([entry]) => {
          if (entry.isIntersecting) {
            el.style.backgroundImage = `url(${url})`;
            el.style.animation = 'none';
            observer.disconnect();
            observer = null;
          }
        }, { rootMargin: '100px' });

        observer.observe(el);
      });
    });

    cleanup(() => { if (observer) observer.disconnect(); });
  });

  // Promo ad interstitial — shows once per visit per branch+version.
  // sessionStorage dies with the tab, so a fresh scan shows the ad again;
  // the version in the key re-shows a replaced image even mid-visit.
  Alpine.data('adOverlay', (branch, version) => ({
    open: false,
    key: 'gaamos-ad-' + branch + '-' + version,
    init() {
      let seen = false;
      try { seen = !!sessionStorage.getItem(this.key); } catch (e) {}
      if (!seen) {
        this.open = true;
        document.body.style.overflow = 'hidden';
      }
    },
    hide() {  // image failed to load — fail open, but don't mark as seen
      this.open = false;
      document.body.style.overflow = '';
    },
    close() {
      this.hide();
      try { sessionStorage.setItem(this.key, '1'); } catch (e) {}
    },
  }));

  Alpine.data('menuApp', () => ({
    // ── Payload (set in init) ──────────────────────────
    restaurant: {},
    branch: {},
    table: null,
    branches: [],
    categories: [],
    dishes: [],

    // ── Navigation ────────────────────────────────────
    screen: 'menu',       // 'menu' | 'detail' | 'cart' | 'placed'
    layout: 'baseline',   // set from payload in init()
    activeCategory: null,
    expandedCategory: null,   // which category's accordion is open (null = none)
    activeSubcat: 'All',

    // ── Overlays ──────────────────────────────────────
    contactOpen: false,
    filterOpen: false,
    lightbox: null,       // image URL shown full-screen (tap-to-zoom), null = closed

    // ── Search ────────────────────────────────────────
    searchOpen: false,
    searchQuery: '',

    // ── Filters ───────────────────────────────────────
    activeDiets: [],

    // ── Detail screen state ───────────────────────────
    selectedDishId: null,
    qty: 1,

    // ── Cart / order ──────────────────────────────────
    cart: [],
    placing: false,
    toast: '',
    orders: [],          // placed orders, persisted on this device (newest first)
    openedOrder: null,   // order shown in the detail modal
    lastOrder: null,     // order just placed, shown on the 'placed' screen (F11)

    // ── Init ──────────────────────────────────────────
    init() {
      const raw = document.getElementById('menu-data');
      if (raw) {
        const data = JSON.parse(raw.textContent);
        this.restaurant = data.restaurant;
        this.branch     = data.branch || {};
        this.table      = data.table || null;
        this.branches   = data.branches;
        this.categories = data.categories;
        this.dishes     = data.dishes;
        this.layout = data.layout || 'baseline';
        // F1: open the first category of THIS venue's menu, never a hardcoded id.
        const first = this.categories[0];
        this.activeCategory = first ? first.id : null;
        this.expandedCategory = this.activeCategory;
      }
      const saved = localStorage.getItem('jc_cart');
      if (saved) {
        try { this.cart = JSON.parse(saved); } catch (e) { this.cart = []; }
      }
      const savedOrders = localStorage.getItem('jc_orders');
      if (savedOrders) {
        try { this.orders = JSON.parse(savedOrders); } catch (e) { this.orders = []; }
      }
      this.initSpy();
    },

    // ── Tabs layout (scroll-spy) ───────────────────────
    spyCategory: null,
    initSpy() {
      if (this.layout !== 'tabs') return;
      this.spyCategory = (this.categories[0] || {}).id || null;
      this.$nextTick(() => {
        const rootEl = this.$refs.tabsBody;
        if (!rootEl || typeof IntersectionObserver === 'undefined') return;
        const obs = new IntersectionObserver(entries => {
          entries.forEach(e => { if (e.isIntersecting) this.spyCategory = e.target.dataset.cat; });
        }, { root: rootEl, rootMargin: '0px 0px -70% 0px' });
        rootEl.querySelectorAll('[data-cat-section]').forEach(el => obs.observe(el));
      });
    },
    jumpTo(catId) {
      this.spyCategory = catId;
      const el = (this.$refs.tabsBody || document).querySelector(`[data-cat-section][data-cat="${catId}"]`);
      if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' });
    },
    sectionGroups(catId) {
      const cat = this.categories.find(c => c.id === catId) || { subcategories: [] };
      let list = this.dishes.filter(d => d.cat === catId);
      if (this.activeDiets.length) list = list.filter(d => this.activeDiets.every(k => d.dietary_tags.includes(k)));
      const subs = (cat.subcategories || []).map(s => s.name);
      if (!subs.length) return list.length ? [{ sub: '', dishes: list }] : [];
      const named = new Set(subs);
      const groups = subs.map(sub => ({ sub, dishes: list.filter(d => d.sub === sub) }));
      const others = list.filter(d => !named.has(d.sub));
      if (others.length) groups.push({ sub: 'Others', dishes: others });
      return groups.filter(g => g.dishes.length > 0);
    },
    subChipsFor(catId) {
      const cat = this.categories.find(c => c.id === catId);
      return cat && cat.subcategories.length ? cat.subcategories.map(s => s.name) : [];
    },

    // ── Helpers ───────────────────────────────────────
    icon(key) { return ICONS[key] || (key ? `<span style="font-size:1.2em;line-height:1;">${key}</span>` : ''); },

    dietClass(tag) { return 'diet ' + (DIET_MAP[tag]?.cls || ''); },
    dietLabel(tag) { return DIET_MAP[tag]?.label || tag; },

    monogram() {
      const words = (this.restaurant.name || '').trim().split(/\s+/).filter(Boolean);
      return words.slice(0, 2).map(w => w[0]).join('').toUpperCase() || '·';
    },

    saveCart() { localStorage.setItem('jc_cart', JSON.stringify(this.cart)); },

    // ── Computed-style getters ─────────────────────────
    get currentCategory() {
      return this.categories.find(c => c.id === this.activeCategory) || { name: '', subcategories: [], hours_note: '', icon_key: '' };
    },
    get currentCategorySubcats() {
      const subs = this.currentCategory.subcategories || [];
      if (!subs.length) return [];
      return [{ name: 'All', icon_key: 'subAll' }, ...subs];
    },
    get filteredDishes() {
      let list = this.dishes.filter(d => d.cat === this.activeCategory);
      if (this.activeSubcat !== 'All') list = list.filter(d => d.sub === this.activeSubcat);
      if (this.activeDiets.length) list = list.filter(d => this.activeDiets.every(k => d.dietary_tags.includes(k)));
      return list;
    },
    // True when the search bar is open with a non-empty query.
    get isSearching() {
      return this.searchOpen && this.searchQuery.trim().length > 0;
    },
    // Global search across the whole menu by name + description,
    // still honouring any active dietary filters.
    get searchResults() {
      const q = this.searchQuery.trim().toLowerCase();
      let list = this.dishes.filter(d =>
        (d.name || '').toLowerCase().includes(q) ||
        (d.description || '').toLowerCase().includes(q)
      );
      if (this.activeDiets.length) list = list.filter(d => this.activeDiets.every(k => d.dietary_tags.includes(k)));
      return list;
    },
    // The list currently driving the menu body (search results or category list).
    get visibleDishes() {
      return this.isSearching ? this.searchResults : this.filteredDishes;
    },
    get groupedDishes() {
      if (this.isSearching) {
        return [{ sub: 'Results', dishes: this.searchResults }];
      }
      const subs = (this.currentCategory.subcategories || []).map(s => s.name);
      if (!subs.length || this.activeSubcat !== 'All') {
        return [{ sub: this.activeSubcat, dishes: this.filteredDishes }];
      }
      const named = new Set(subs);
      const groups = subs.map(sub => ({ sub, dishes: this.filteredDishes.filter(d => d.sub === sub) }));
      // F14: dishes whose sub matches no named subcategory must still render.
      const others = this.filteredDishes.filter(d => !named.has(d.sub));
      if (others.length) groups.push({ sub: 'Others', dishes: others });
      return groups.filter(g => g.dishes.length > 0);
    },
    get selectedDish() {
      return this.dishes.find(d => d.id === this.selectedDishId) || null;
    },
    get cartCount() {
      return this.cart.reduce((n, c) => n + c.qty, 0);
    },
    get detailTotal() {
      if (!this.selectedDish) return 0;
      return this.selectedDish.price * Math.max(1, this.cartQtyOf(this.selectedDish.id));
    },
    cartSubtotal() { return this.cart.reduce((s, c) => s + c.price * c.qty, 0); },
    cartTotal()     { return this.cartSubtotal(); },
    categoryDishCount(catId) { return this.dishes.filter(d => d.cat === catId).length; },
    subcatDishCount(sub) {
      if (sub === 'All') return this.dishes.filter(d => d.cat === this.activeCategory).length;
      return this.dishes.filter(d => d.cat === this.activeCategory && d.sub === sub).length;
    },
    showGroupHeader() {
      if (this.isSearching) return false;
      return this.activeSubcat === 'All' && (this.currentCategory.subcategories || []).length > 0;
    },

    // ── Actions ───────────────────────────────────────
    setCategory(id) {
      this.activeCategory = id;
      this.activeSubcat   = 'All';
      this.activeDiets    = [];
    },
    toggleCategory(id) {
      // Clicking the open category closes its accordion; clicking another opens it.
      if (this.expandedCategory === id) {
        this.expandedCategory = null;
      } else {
        if (this.activeCategory !== id) this.setCategory(id);
        this.expandedCategory = id;
      }
    },
    openSearch() {
      this.searchOpen = true;
      this.$nextTick(() => { this.$refs.searchInput && this.$refs.searchInput.focus(); });
    },
    closeSearch() {
      this.searchOpen  = false;
      this.searchQuery = '';
    },
    openDish(id) {
      // Keep category context in sync (a search hit may live in another category)
      // so the detail screen shows the correct category label.
      const dish = this.dishes.find(d => d.id === id);
      if (dish && dish.cat && dish.cat !== this.activeCategory) {
        this.activeCategory   = dish.cat;
        this.expandedCategory = dish.cat;
        this.activeSubcat     = 'All';
      }
      this.selectedDishId  = id;
      this.qty             = 1;
      this.screen          = 'detail';
    },
    addToCart() {
      if (!this.selectedDish) return;
      this.addQty(this.selectedDish.id, this.qty);
      this.screen = 'menu';
    },
    quickAdd(dishId) { this.addQty(dishId, 1); },
    addQty(dishId, n) {
      const dish = this.dishes.find(d => d.id === dishId);
      if (!dish) return;
      const idx = this.cart.findIndex(c => c.id === String(dish.id));
      if (idx >= 0) { this.cart[idx].qty += n; }
      else { this.cart.push({ id: String(dish.id), name: dish.name, image_url: dish.image_url, qty: n, price: dish.price }); }
      this.saveCart();
    },
    quickRemove(dishId) {
      const idx = this.cart.findIndex(c => c.id === String(dishId));
      if (idx >= 0) this.updateCartQty(idx, -1);
    },
    cartQtyOf(dishId) {
      const line = this.cart.find(c => c.id === String(dishId));
      return line ? line.qty : 0;
    },
    updateCartQty(idx, delta) {
      const next = this.cart[idx].qty + delta;
      if (next <= 0) { this.cart.splice(idx, 1); }
      else { this.cart[idx].qty = next; }
      this.saveCart();
    },
    removeFromCart(idx) {
      this.cart.splice(idx, 1);
      this.saveCart();
    },
    clearCart() { this.cart = []; this.saveCart(); },
    showToast(msg) {
      this.toast = msg;
      clearTimeout(this._toastT);
      this._toastT = setTimeout(() => { this.toast = ''; }, 2600);
    },
    saveOrders() { localStorage.setItem('jc_orders', JSON.stringify(this.orders)); },
    placeOrder() {
      if (this.placing || this.cart.length === 0) return;
      this.placing = true;
      const items = this.cart.map(c => ({ id: Number(c.id), qty: c.qty }));
      // Snapshot the order for this device's record before clearing the cart.
      const record = {
        id: Date.now(),
        placed_at: new Date().toISOString(),
        items: this.cart.map(c => ({ name: c.name, qty: c.qty, price: c.price, image_url: c.image_url })),
        total: this.cartTotal(),
      };
      fetch('/api/order/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCookie('csrftoken') },
        body: JSON.stringify({ branch: this.branch.slug, table: this.table ? this.table.code : null, items }),
      })
        .then(r => r.json())
        .then((res) => {
          record.number = res.number;
          this.orders.unshift(record);
          this.saveOrders();
          this.clearCart();
          this.lastOrder = record;
          this.screen = 'placed';
        })
        .catch(() => { this.showToast('Could not place order — try again'); })
        .finally(() => { this.placing = false; });
    },
    orderTime(o) {
      if (!o || !o.placed_at) return '';
      const d = new Date(o.placed_at);
      const today = new Date();
      const sameDay = d.toDateString() === today.toDateString();
      const t = d.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
      return sameDay ? `Today, ${t}` : `${d.toLocaleDateString([], { day: 'numeric', month: 'short' })}, ${t}`;
    },
    openOrder(o) { this.openedOrder = o; },
    deleteOrder(id) {
      this.orders = this.orders.filter(o => o.id !== id);
      this.saveOrders();
      this.openedOrder = null;
    },
    toggleDiet(key) {
      const i = this.activeDiets.indexOf(key);
      if (i >= 0) this.activeDiets.splice(i, 1); else this.activeDiets.push(key);
    },
    goBack() { this.screen = 'menu'; this.selectedDishId = null; this.lastOrder = null; },
  }));
});

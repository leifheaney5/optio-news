// Attach Flask-WTF's token to same-origin state-changing requests.
(() => {
    const nativeFetch = window.fetch.bind(window);
    const mutatingMethods = new Set(['POST', 'PUT', 'PATCH', 'DELETE']);

    window.fetch = (input, init) => {
        const request = input instanceof Request ? input : null;
        const method = String((init && init.method) || (request && request.method) || 'GET').toUpperCase();
        const url = new URL(request ? request.url : input, window.location.href);

        if (!mutatingMethods.has(method) || url.origin !== window.location.origin) {
            return nativeFetch(input, init);
        }

        const headers = new Headers(request ? request.headers : undefined);
        if (init && init.headers) {
            new Headers(init.headers).forEach((value, key) => headers.set(key, value));
        }
        const token = document.querySelector('meta[name="csrf-token"]')?.content;
        if (token) headers.set('X-CSRFToken', token);

        const nextInit = init ? { ...init, headers } : { headers };
        return nativeFetch(input, nextInit);
    };
})();

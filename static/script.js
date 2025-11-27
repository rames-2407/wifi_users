// Auto-dismiss alerts
document.addEventListener('DOMContentLoaded', function() {
    // Auto-dismiss success alerts after 5 seconds
    setTimeout(function() {
        const alerts = document.querySelectorAll('.alert-success, .alert-info');
        alerts.forEach(function(alert) {
            const bsAlert = new bootstrap.Alert(alert);
            bsAlert.close();
        });
    }, 5000);
    
    // MAC address formatting
    const macInput = document.querySelector('#mac_address');

    if (macInput) {
        // Format input on typing
        macInput.addEventListener('input', function (e) {
            let value = e.target.value.replace(/[^0-9A-Fa-f]/g, '');
            let formatted = value.match(/.{1,2}/g)?.join(':') || value;
            e.target.value = formatted.substring(0, 17).toUpperCase();
        });

        // Validate on blur or form submission
        macInput.addEventListener('blur', function (e) {
            validateMAC();
        });

        const validateMAC = () => {
            const macValue = macInput.value.trim();
            const macRegex = /^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$/;

            if (!macRegex.test(macValue)) {
                macInput.classList.add('is-invalid');
                return false;
            } else {
                macInput.classList.remove('is-invalid');
                return true;
            }
        };

        const form = macInput.closest('form');
        if (form) {
            form.addEventListener('submit', function (e) {
                if (!validateMAC()) {
                    e.preventDefault();
                    macInput.focus();
                }
            });
        }
    }
});

document.addEventListener('DOMContentLoaded', function () {
    const toasts = document.querySelectorAll('.toast');
    toasts.forEach(function (toastEl) {
        const bsToast = new bootstrap.Toast(toastEl, { delay: 2000 });
        bsToast.show();
    });
});


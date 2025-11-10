// Additional JavaScript functionality can be added here

// Form validation
document.addEventListener('DOMContentLoaded', function() {
    // Index number format validation
    const indexInputs = document.querySelectorAll('input[name="index_number"]');
    indexInputs.forEach(input => {
        input.addEventListener('blur', function() {
            const pattern = /^\d{11}\/\d{4}$/;
            if (!pattern.test(this.value)) {
                this.classList.add('is-invalid');
            } else {
                this.classList.remove('is-invalid');
            }
        });
    });
    
    // Phone number format validation
    const phoneInputs = document.querySelectorAll('input[name="phone"]');
    phoneInputs.forEach(input => {
        input.addEventListener('blur', function() {
            const pattern = /^2547\d{8}$/;
            if (!pattern.test(this.value)) {
                this.classList.add('is-invalid');
            } else {
                this.classList.remove('is-invalid');
            }
        });
    });
});
// Auto-calculation functions for Lot <-> KG conversion
document.addEventListener('DOMContentLoaded', function() {
    const lotWeightInput = document.getElementById('lot_weight_val');
    const LOT_WEIGHT = lotWeightInput ? parseFloat(lotWeightInput.value) : 20;

    // Purchase / Sale Lot & KG calculation listeners
    const lotsInput = document.getElementById('lots');
    const kgInput = document.getElementById('kg');
    const rateInput = document.getElementById('rate');
    const grossInput = document.getElementById('gross_amount');

    if (lotsInput && kgInput) {
        lotsInput.addEventListener('input', function() {
            const lots = parseFloat(this.value) || 0;
            kgInput.value = (lots * LOT_WEIGHT).toFixed(2);
            calculateGross();
        });

        kgInput.addEventListener('input', function() {
            const kg = parseFloat(this.value) || 0;
            lotsInput.value = (kg / LOT_WEIGHT).toFixed(2);
            calculateGross();
        });
    }

    if (rateInput) {
        rateInput.addEventListener('input', calculateGross);
    }

    function calculateGross() {
        if (kgInput && rateInput && grossInput) {
            const kg = parseFloat(kgInput.value) || 0;
            const rate = parseFloat(rateInput.value) || 0;
            grossInput.value = (kg * rate).toFixed(2);
            if (typeof calculateFinal === 'function') calculateFinal();
        }
    }
});
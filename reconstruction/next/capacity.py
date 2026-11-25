"""Proportional class mix in integer hundredths of PCE."""
from decimal import Decimal
def allocate(cars,motors,policy):
    if min(cars,motors)<0: raise ValueError("Negative stock")
    unit=policy["motor_units"]
    cap=int(Decimal(policy["capacity_units"])*Decimal(str(policy["fill_fraction"])))
    total=100*cars+unit*motors
    if total<=cap:return cars,motors
    c=cars*cap//total;m=motors*cap//total
    remaining=cap-100*c-unit*m
    # Largest remainder first; fill available residual capacity without overshoot.
    order=sorted(((cars*cap%total,"car"),(motors*cap%total,"motor")),reverse=True)
    for _,kind in order:
        if kind=="car":
            n=min(cars-c,remaining//100);c+=n;remaining-=100*n
        else:
            n=min(motors-m,remaining//unit);m+=n;remaining-=unit*n
    return c,m

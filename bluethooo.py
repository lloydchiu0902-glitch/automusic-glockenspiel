import asyncio
from bleak import BleakScanner

async def scan_devices():
    print("Scanning for BLE devices (ensure module is powered on)...\n")
    devices = await BleakScanner.discover(timeout=5.0)
    
    if not devices:
        print("No BLE devices found. Check Bluetooth settings and module power.")
        return

    print("Found BLE devices:")
    print("-" * 50)
    for d in devices:
        # Filter out unnamed devices
        name = d.name or "Unknown"
        print(f"Name: {name:<20} | MAC: {d.address}")
    print("-" * 50)
    print("\nLook for devices like 'HMSoft', 'BT05', 'JDY-18', or 'DSD TECH'.")
    print("Copy the MAC address to the Castella input field.")

if __name__ == "__main__":
    asyncio.run(scan_devices())
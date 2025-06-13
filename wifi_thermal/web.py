import re
import json
import asyncio
import time

import cv2
import websockets
import numpy as np

# --- Configuration Parameters ---
# WebSocket server address
SERVER_URI = 'ws://thermal.local:81'
# OpenCV display window name
WINDOW_NAME = 'Thermal Camera (Press "q" or ESC to quit)'
# Image magnification factor
DISPLAY_SCALE = 15
# Temperature range for color mapping (Celsius)
# Setting this range narrower can enhance contrast
MIN_TEMP = 00.0
MAX_TEMP = 30.0

# Global variable to control the main loop execution
running = True

# FPS calculation variables
frame_count = 0
fps = 0.0
fps_start_time = time.time()

# Precompile run-length encoding pattern and difference map for performance
RLE_PATTERN = re.compile(r"(\d*)(\D)")
POSITIVE_CHARS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
NEGATIVE_CHARS = "abcdefghijklmnopqrstuvwxyz"
DIFF_MAP = {p: i for i, p in enumerate(POSITIVE_CHARS)}
DIFF_MAP.update({n: -i for i, n in enumerate(NEGATIVE_CHARS) if i > 0})


from time import perf_counter

def time_it(func):
    """
    Decorator to measure the execution time of a function.
    Prints the time taken to execute the function.
    """
    def wrapper(*args, **kwargs):
        start_time = perf_counter()
        result = func(*args, **kwargs)
        end_time = perf_counter()
        print(f"Function '{func.__name__}' executed in {(end_time - start_time) * 1000:.4f} ms")
        return result
    return wrapper


@time_it
def decode_thermal_data(compressed_data: str) -> np.ndarray:
    """
    Decodes a compressed string from the ESP32 and MLX90640 thermal camera firmware.
    (This function is largely the same as the previous version, only the return type is explicitly np.ndarray)

    Args:
        compressed_data: String containing the compressed data.

    Returns:
        A NumPy array of 768 floating-point temperature values.
        Returns an empty array if the input string format is incorrect.
    """
    data_str = ""
    try:
        data_str = compressed_data
    except (json.JSONDecodeError, KeyError, TypeError):
        print(f"Error decoding data: {compressed_data}")
        return np.array([])

    try:
        header_end_pos = data_str.find('.')
        if header_end_pos == -1:
            print(f"Error: Header not found in data: {data_str}")
            return np.array([])
        num_decimals = int(data_str[0])
        accuracy = int(data_str[1])
        initial_scaled_value = int(data_str[2:header_end_pos])
        encoded_data = data_str[header_end_pos + 1:]
    except (ValueError, IndexError):
        print(f"Error parsing header from data: {data_str}")
        return np.array([])

    # Efficient run-length decoding using precompiled regex
    diff_indices = []
    for count_str, char in RLE_PATTERN.findall(encoded_data):
        count = int(count_str) if count_str else 1
        diff_indices.extend([DIFF_MAP.get(char, 0)] * count)
    if len(diff_indices) != 767:
        print(f"Warning: Expected 767 decoded values, but got {len(diff_indices)}.")

    temperatures = np.zeros(768, dtype=np.float32)
    power_of_10 = 10**num_decimals
    column_count = 32

    temperatures[0] = initial_scaled_value / power_of_10
    processed_previous_value = initial_scaled_value

    for x in range(1, 768):
        if x - 1 >= len(diff_indices): break
        diff_index = diff_indices[x - 1]

        if x % column_count == 0:
            ref_temp = temperatures[x - column_count]
            scaled_ref = round(ref_temp * power_of_10)
            reference_value = scaled_ref - (scaled_ref % accuracy)
        else:
            reference_value = processed_previous_value
            
        current_scaled_value = reference_value + diff_index * accuracy
        temperatures[x] = current_scaled_value / power_of_10
        processed_previous_value = current_scaled_value

    return temperatures


@time_it
def update(data: str):
    """Decodes, processes, and displays the thermal map using OpenCV"""
    global running, frame_count, fps, fps_start_time

    # 1. Decode data
    temperatures = decode_thermal_data(data)
    if temperatures.size != 768:
        print(f"Error: Decoded temperature data size is incorrect, got {temperatures.size}, expected 768.")
        return
    
    # Reshape the 1D array into a 24x32 image
    thermal_array = temperatures.reshape((24, 32))

    # 2. Normalize temperature data to 0-255 to apply colormap
    # First, clip temperature values to the defined MIN/MAX range
    clipped_array = np.clip(thermal_array, MIN_TEMP, MAX_TEMP)
    # Then, linearly map to 0-255
    normalized_array = 255 * (clipped_array - MIN_TEMP) / (MAX_TEMP - MIN_TEMP)
    # Convert to 8-bit unsigned integer
    normalized_array = normalized_array.astype(np.uint8)

    # 3. Apply colormap
    colored_image = cv2.applyColorMap(normalized_array, cv2.COLORMAP_INFERNO)

    # 4. Enlarge the image for observation
    (height, width, _) = colored_image.shape
    resized_image = cv2.resize(
        colored_image, 
        (width * DISPLAY_SCALE, height * DISPLAY_SCALE), 
        interpolation=cv2.INTER_NEAREST # Use nearest-neighbor interpolation to preserve pixelation
    )

    # Overlay FPS on the image
    cv2.putText(resized_image, f"FPS: {fps:.2f}", (10, 30),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)

    # 5. Display the image
    cv2.imshow(WINDOW_NAME, resized_image)

    # 6. Check for key presses, if 'q' or ESC is pressed, exit
    key = cv2.waitKey(1) & 0xFF
    if key == ord('q') or key == 27: # 27 is the ASCII code for ESC key
        running = False

    # FPS calculation
    frame_count += 1
    elapsed_time = time.time() - fps_start_time
    if elapsed_time > 1.0:
        fps = frame_count / elapsed_time
        frame_count = 0
        fps_start_time = time.time()


async def listen_for_data():
    """Receives data from the WebSocket server and updates the display"""
    print(f"Attempting to connect to WebSocket server: {SERVER_URI}...")
    global running
    try:
        async with websockets.connect(SERVER_URI) as websocket:
            print("Successfully connected to WebSocket server.")
            # Use the global running flag to control the loop
            while running:
                try:
                    # Set a timeout to allow cv2.waitKey() to be detected
                    message = await asyncio.wait_for(websocket.recv(), timeout=0.1)
                    data = eval(message)
                    if 'data' in data:
                        update(data['data'])
                except asyncio.TimeoutError:
                    continue
                except websockets.exceptions.ConnectionClosed:
                    print("WebSocket connection closed.")
                    break
                except Exception as e:
                    print(f"Error processing message: {e}")
    except Exception as e:
        print(f"Failed to connect to WebSocket or other error occurred: {e}")
    finally:
        # Ensure the main loop also stops if the connection fails or is disconnected
        running = False


async def main():
    await listen_for_data()


if __name__ == "__main__":
    try:
        # Run the asynchronous event loop
        asyncio.run(main())
    finally:
        # Ensure all OpenCV windows are closed when the program ends
        cv2.destroyAllWindows()
        print("Windows closed, program ended.")
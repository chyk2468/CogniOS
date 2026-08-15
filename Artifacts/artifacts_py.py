def bubble_sort(arr):
    """
    Sorts a list of numbers using the Bubble Sort algorithm.
    The algorithm repeatedly passes through the list, compares adjacent 
    elements, and swaps them if they are in the wrong order.
    """
    n = len(arr)
    # Traverse through all array elements
    for i in range(n):
        swapped = False
        # Last i elements are already in place
        for j in range(0, n - i - 1):
            # Swap if the element seen is greater than the next element
            if arr[j] > arr[j + 1]:
                arr[j], arr[j + 1] = arr[j + 1], arr[j]
                swapped = True
        
        # Optimization: if no two elements were swapped by inner loop, then the array is sorted
        if not swapped:
            break
    
    return arr

# --- Example Usage ---
if __name__ == "__main__":
    my_list = [5, 2, 8, 1, 9]
    print(f"Original list: {my_list}")
    
    sorted_list = bubble_sort(my_list.copy())
    print(f"Sorted list: {sorted_list}")

    another_list = [45, 30, 20, 1]
    print(f"\nOriginal list: {another_list}")
    bubble_sort(another_list) # Sorting in place for demonstration
    print(f"Sorted list: {another_list}")
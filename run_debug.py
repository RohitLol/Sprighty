import sys
import traceback

try:
    sys.path.insert(0, ".")
    from main import main
    main()
except Exception as e:
    with open("crash.log", "w") as f:
        traceback.print_exc(file=f)
    print(traceback.format_exc())
    input("Press Enter to exit...")
